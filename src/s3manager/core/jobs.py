"""비동기 잡 매니저.

ThreadPoolExecutor로 전송 작업을 실행하고,
잡별 진행률 이벤트를 asyncio 큐로 push한다.
취소와 이력 보관을 지원한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from s3manager.core import s3_engine
from s3manager.core import sftp_engine

logger = logging.getLogger(__name__)

# 진행률 WebSocket 이벤트 throttle 간격 (초)
PROGRESS_THROTTLE_SEC = 0.2

# 이력 최대 보관 수
MAX_JOB_HISTORY = 100


# ---------------------------------------------------------------------------
# 잡 상태 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class JobState:
    """단일 잡의 상태를 보관한다."""

    job_id: str
    kind: str  # "download" | "upload" | "sync"
    local_dir: str = ""  # reveal/Finder 열기용 로컬 경로
    status: str = "pending"  # "pending"|"running"|"done"|"error"|"canceled"
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    total_bytes: int = 0
    transferred_bytes: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    current_file: str = ""

    # WebSocket 구독자 큐 목록 (asyncio.Queue)
    _queues: list[asyncio.Queue] = field(default_factory=list, repr=False)
    # 취소 이벤트
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    # 마지막 progress 이벤트 발송 시각
    _last_progress_ts: float = field(default=0.0, repr=False)
    # 전송 시작 시각(속도 계산용)
    _transfer_start: float = field(default=0.0, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Job 모델에 맞는 딕셔너리(camelCase)를 반환한다."""
        return {
            "jobId": self.job_id,
            "kind": self.kind,
            "localDir": self.local_dir,
            "status": self.status,
            "totalFiles": self.total_files,
            "completedFiles": self.completed_files,
            "failedFiles": self.failed_files,
            "totalBytes": self.total_bytes,
            "transferredBytes": self.transferred_bytes,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# 잡 매니저 싱글톤
# ---------------------------------------------------------------------------

class JobManager:
    """비동기 잡 매니저.

    스레드풀에서 전송 작업을 실행하고,
    이벤트를 asyncio 큐로 push하여 WebSocket 핸들러에 전달한다.
    """

    def __init__(self, max_workers: int = 10) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job-worker")
        self._jobs: dict[str, JobState] = {}  # jobId → JobState
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """asyncio 이벤트 루프를 주입한다. 앱 시작 시 호출."""
        self._loop = loop

    # ------------------------------------------------------------------
    # 잡 등록 및 조회
    # ------------------------------------------------------------------

    def _new_job(self, kind: str, local_dir: str = "") -> JobState:
        job = JobState(job_id=str(uuid.uuid4()), kind=kind, local_dir=local_dir)
        with self._lock:
            self._jobs[job.job_id] = job
            # 이력 최대치 초과 시 가장 오래된 완료 잡 제거
            completed = [
                j for j in self._jobs.values()
                if j.status in ("done", "error", "canceled")
            ]
            if len(completed) > MAX_JOB_HISTORY:
                oldest = sorted(completed, key=lambda j: j.finished_at or datetime.min)[0]
                del self._jobs[oldest.job_id]
        return job

    def get_job(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobState]:
        """최신순으로 정렬된 잡 목록을 반환한다."""
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(
            jobs,
            key=lambda j: (j.started_at or j.finished_at or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )

    def cancel_job(self, job_id: str) -> bool:
        """잡 취소 요청. running/pending 상태에서만 유효."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status not in ("pending", "running"):
            return False
        job._cancel_event.set()
        logger.info("잡 취소 요청: %s", job_id)
        return True

    # ------------------------------------------------------------------
    # WebSocket 구독
    # ------------------------------------------------------------------

    def subscribe(self, job_id: str) -> asyncio.Queue | None:
        """잡 이벤트 큐를 생성하고 반환한다."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        job._queues.append(q)
        return q

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        """큐 구독을 해제한다."""
        job = self._jobs.get(job_id)
        if job and queue in job._queues:
            job._queues.remove(queue)

    def _push_event(self, job: JobState, event: dict) -> None:
        """모든 구독 큐에 이벤트를 push한다. 스레드-세이프."""
        if not self._loop:
            return
        for q in list(job._queues):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except asyncio.QueueFull:
                logger.warning("잡 이벤트 큐 가득 참 (job_id=%s)", job.job_id)
            except Exception as exc:
                logger.debug("이벤트 push 실패: %s", exc)

    # ------------------------------------------------------------------
    # 진행률 콜백 팩토리
    # ------------------------------------------------------------------

    def _make_callbacks(self, job: JobState):
        """잡에 연결된 on_bytes / on_file 콜백을 반환한다."""

        def on_bytes(n: int) -> None:
            job.transferred_bytes += n
            now = time.monotonic()
            if now - job._last_progress_ts < PROGRESS_THROTTLE_SEC:
                return
            job._last_progress_ts = now

            elapsed = now - job._transfer_start if job._transfer_start else 1e-9
            speed = job.transferred_bytes / elapsed if elapsed > 0 else 0
            remaining = job.total_bytes - job.transferred_bytes
            eta = int(remaining / speed) if speed > 0 else None

            self._push_event(
                job,
                {
                    "type": "progress",
                    "completedFiles": job.completed_files,
                    "totalFiles": job.total_files,
                    "transferredBytes": job.transferred_bytes,
                    "totalBytes": job.total_bytes,
                    "currentFile": job.current_file,
                    "speedBps": round(speed),
                    "etaSec": eta,
                },
            )

        def on_file(key: str, success: bool, error_msg: str | None) -> None:
            if success:
                job.completed_files += 1
            else:
                job.failed_files += 1
            job.current_file = key
            self._push_event(
                job,
                {
                    "type": "file",
                    "key": key,
                    "status": "done" if success else "failed",
                    "error": error_msg,
                },
            )

        return on_bytes, on_file

    # ------------------------------------------------------------------
    # 잡 실행 진입점
    # ------------------------------------------------------------------

    def _run_job(self, job: JobState, task_fn) -> None:
        """스레드풀 워커에서 실행되는 잡 본체."""
        job.status = "running"
        job.started_at = datetime.now(tz=timezone.utc)
        job._transfer_start = time.monotonic()
        self._push_event(job, {"type": "start", "job": job.to_dict()})

        try:
            success, failure = task_fn()
        except Exception as exc:
            logger.exception("잡 실행 중 예외 (job_id=%s): %s", job.job_id, exc)
            job.status = "error"
            job.error = str(exc)
            job.finished_at = datetime.now(tz=timezone.utc)
            self._push_event(job, {"type": "error", "message": str(exc)})
            return

        job.finished_at = datetime.now(tz=timezone.utc)
        elapsed = (job.finished_at - job.started_at).total_seconds()

        if job._cancel_event.is_set():
            job.status = "canceled"
            self._push_event(job, {"type": "canceled"})
        else:
            job.status = "done"
            self._push_event(
                job,
                {
                    "type": "done",
                    "success": success,
                    "failure": failure,
                    "elapsedSec": round(elapsed, 2),
                },
            )

    # ------------------------------------------------------------------
    # 공개 잡 생성 메서드
    # ------------------------------------------------------------------

    def submit_download(
        self,
        s3_client,
        bucket: str,
        local_dir: str,
        *,
        prefix: str | None = None,
        keys: list[str] | None = None,
        max_workers: int = 5,
    ) -> str:
        """다운로드 잡을 생성하고 jobId를 반환한다."""
        job = self._new_job("download", local_dir=local_dir)

        # 총 크기/파일 수 미리 파악 (best-effort, 실패해도 잡은 진행)
        try:
            if prefix is not None:
                summary = s3_engine.flat_summary(s3_client, bucket, prefix)
                job.total_files = summary["totalFiles"]
                job.total_bytes = summary["totalBytes"]
            elif keys:
                job.total_files = len(keys)
        except Exception:
            pass

        on_bytes, on_file = self._make_callbacks(job)

        def task():
            return s3_engine.download_objects(
                s3_client,
                bucket,
                local_dir,
                prefix=prefix,
                keys=keys,
                max_workers=max_workers,
                on_bytes=on_bytes,
                on_file=on_file,
                cancel_event=job._cancel_event,
            )

        self._executor.submit(self._run_job, job, task)
        return job.job_id

    def submit_upload(
        self,
        s3_client,
        bucket: str,
        prefix: str,
        local_paths: list[str],
        *,
        max_workers: int = 5,
    ) -> str:
        """업로드 잡을 생성하고 jobId를 반환한다."""
        # reveal용: 업로드 소스의 상위 폴더(첫 경로 기준)
        src_dir = os.path.dirname(local_paths[0]) if local_paths else ""
        job = self._new_job("upload", local_dir=src_dir)

        on_bytes, on_file = self._make_callbacks(job)

        def task():
            return s3_engine.upload_objects(
                s3_client,
                bucket,
                prefix,
                local_paths,
                max_workers=max_workers,
                on_bytes=on_bytes,
                on_file=on_file,
                cancel_event=job._cancel_event,
            )

        self._executor.submit(self._run_job, job, task)
        return job.job_id

    # ------------------------------------------------------------------
    # 원격(SFTP) 잡
    # ------------------------------------------------------------------

    def submit_remote_download(
        self,
        ssh,
        local_dir: str,
        *,
        remote_dir: str | None = None,
        keys: list[str] | None = None,
        max_workers: int = 4,
    ) -> str:
        """원격 → 로컬 다운로드 잡을 생성하고 jobId를 반환한다."""
        job = self._new_job("remote-download", local_dir=local_dir)

        # 총 크기/파일 수 미리 파악 (best-effort)
        try:
            if remote_dir is not None:
                summary = sftp_engine.flat_summary(ssh, remote_dir)
                job.total_files = summary["totalFiles"]
                job.total_bytes = summary["totalBytes"]
            elif keys:
                job.total_files = len(keys)
        except Exception:
            pass

        on_bytes, on_file = self._make_callbacks(job)

        def task():
            return sftp_engine.download_files(
                ssh,
                local_dir,
                remote_dir=remote_dir,
                keys=keys,
                max_workers=max_workers,
                on_bytes=on_bytes,
                on_file=on_file,
                cancel_event=job._cancel_event,
            )

        self._executor.submit(self._run_job, job, task)
        return job.job_id

    def submit_remote_upload(
        self,
        ssh,
        remote_dir: str,
        local_paths: list[str],
        *,
        max_workers: int = 4,
    ) -> str:
        """로컬 → 원격 업로드 잡을 생성하고 jobId를 반환한다."""
        src_dir = os.path.dirname(local_paths[0]) if local_paths else ""
        job = self._new_job("remote-upload", local_dir=src_dir)

        on_bytes, on_file = self._make_callbacks(job)

        def task():
            return sftp_engine.upload_files(
                ssh,
                remote_dir,
                local_paths,
                max_workers=max_workers,
                on_bytes=on_bytes,
                on_file=on_file,
                cancel_event=job._cancel_event,
            )

        self._executor.submit(self._run_job, job, task)
        return job.job_id


# 모듈 수준 싱글톤
job_manager = JobManager()
