"""SFTP(원격서버) 작업 엔진.

paramiko를 사용해 list / download / upload 기능을 콜백 기반으로 제공한다.
s3_engine과 동일한 콜백 시그니처(BytesCallback / FileCallback)와
동일한 list 반환 형태({folders, objects})를 사용해 잡 매니저·프론트 트리를 재사용한다.

스레드 안전성: paramiko SFTPClient는 단일 채널을 동시에 쓰면 안전하지 않으므로,
각 전송 워커는 SSHClient(Transport)에서 자신의 SFTP 채널을 새로 연다.
"""

from __future__ import annotations

import logging
import os
import posixpath
import queue
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import paramiko

logger = logging.getLogger(__name__)

# s3_engine과 동일한 콜백 타입
BytesCallback = Callable[[int], None]  # 전송된 바이트 증분 콜백
FileCallback = Callable[[str, bool, str | None], None]  # (path, success, error_msg)


# ---------------------------------------------------------------------------
# 연결
# ---------------------------------------------------------------------------

def connect(
    host: str,
    port: int,
    username: str,
    *,
    key_path: str | None = None,
    key_passphrase: str | None = None,
    password: str | None = None,
    timeout: int = 15,
) -> paramiko.SSHClient:
    """SSH 연결을 맺고 SSHClient를 반환한다.

    key_path가 주어지면 해당 키로, 없으면 ~/.ssh 기본 키·ssh-agent·password를 시도한다.
    호스트 키 검증은 편의를 위해 AutoAddPolicy를 사용한다(개인용 도구).

    Raises:
        paramiko/소켓 예외 — 호출자가 처리.
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": timeout,
        "allow_agent": True,
        "look_for_keys": True,
    }
    if key_path:
        connect_kwargs["key_filename"] = str(Path(key_path).expanduser())
        if key_passphrase:
            connect_kwargs["passphrase"] = key_passphrase
    if password:
        connect_kwargs["password"] = password
        # 명시적 password 인증 시 키 자동 탐색은 끈다(불필요한 지연/실패 방지)
        if not key_path:
            connect_kwargs["look_for_keys"] = False

    client.connect(**connect_kwargs)
    return client


def _open_sftp_retry(
    ssh: paramiko.SSHClient, attempts: int = 3, delay: float = 0.5
) -> paramiko.SFTPClient:
    """SFTP 채널을 연다. 일시적 채널 거부(MaxSessions 등)에 대비해 재시도한다."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return ssh.open_sftp()
        except Exception as exc:  # ChannelException 포함
            last = exc
            if i < attempts - 1:
                time.sleep(delay)
    assert last is not None
    raise last


def home_dir(ssh: paramiko.SSHClient) -> str:
    """원격 홈 디렉터리(또는 현재 작업 디렉터리)의 절대 경로를 반환한다."""
    sftp = _open_sftp_retry(ssh)
    try:
        return sftp.normalize(".")
    finally:
        sftp.close()


# ---------------------------------------------------------------------------
# 탐색 (list)
# ---------------------------------------------------------------------------

def _to_iso(mtime: float) -> str:
    """epoch 초를 ISO8601 문자열로 변환한다."""
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def list_one_level(ssh: paramiko.SSHClient, path: str = "") -> dict[str, list]:
    """path 디렉터리의 한 레벨만 열거한다.

    s3_engine.list_one_level과 동일한 형태를 반환한다.
    폴더 key는 트레일링 슬래시를 포함한다(S3 규약과 일치).

    Returns:
        {"folders": [{"key", "name", "isFolder": True}, ...],
         "objects": [{"key", "size", "lastModified", "isFolder": False}, ...]}
    """
    sftp = _open_sftp_retry(ssh)
    try:
        base = sftp.normalize(path) if path else sftp.normalize(".")
        entries = sftp.listdir_attr(base)
    finally:
        sftp.close()

    folders = []
    objects = []
    for attr in entries:
        name = attr.filename
        if name in (".", ".."):
            continue
        full = posixpath.join(base, name)
        mode = attr.st_mode or 0
        if stat.S_ISDIR(mode):
            folders.append({"key": full + "/", "name": name, "isFolder": True})
        elif stat.S_ISREG(mode):
            objects.append(
                {
                    "key": full,
                    "size": attr.st_size or 0,
                    "lastModified": _to_iso(attr.st_mtime or 0),
                    "isFolder": False,
                }
            )
        # 심볼릭 링크/특수 파일은 건너뛴다

    folders.sort(key=lambda f: f["name"].lower())
    objects.sort(key=lambda o: posixpath.basename(o["key"]).lower())
    return {"folders": folders, "objects": objects}


def list_all_files(ssh: paramiko.SSHClient, remote_dir: str) -> list[dict]:
    """remote_dir 하위의 모든 일반 파일을 재귀적으로 열거한다.

    Returns:
        [{"key": 절대경로, "size": N, "lastModified": "ISO", "isFolder": False}, ...]
    """
    sftp = _open_sftp_retry(ssh)
    results: list[dict] = []
    try:
        base = sftp.normalize(remote_dir)

        def _walk(d: str) -> None:
            for attr in sftp.listdir_attr(d):
                name = attr.filename
                if name in (".", ".."):
                    continue
                full = posixpath.join(d, name)
                mode = attr.st_mode or 0
                if stat.S_ISDIR(mode):
                    _walk(full)
                elif stat.S_ISREG(mode):
                    results.append(
                        {
                            "key": full,
                            "size": attr.st_size or 0,
                            "lastModified": _to_iso(attr.st_mtime or 0),
                            "isFolder": False,
                        }
                    )

        _walk(base)
    finally:
        sftp.close()
    return results


def flat_summary(ssh: paramiko.SSHClient, remote_dir: str) -> dict[str, int]:
    """remote_dir 하위 전체 파일 수와 총 바이트를 반환한다."""
    files = list_all_files(ssh, remote_dir)
    return {"totalFiles": len(files), "totalBytes": sum(f["size"] for f in files)}


# ---------------------------------------------------------------------------
# 진행률 콜백 어댑터
# ---------------------------------------------------------------------------

class _IncrementalCallback:
    """paramiko의 누적(cumulative) 진행 콜백을 증분(delta) 콜백으로 변환한다.

    paramiko get/put 콜백은 파일별로 (transferred, total) 누적값을 전달하므로,
    파일 1건당 인스턴스 1개를 사용해 직전 값과의 차이를 외부 on_bytes로 보낸다.
    """

    def __init__(self, on_bytes: BytesCallback) -> None:
        self._on_bytes = on_bytes
        self._last = 0

    def __call__(self, transferred: int, total: int) -> None:
        delta = transferred - self._last
        self._last = transferred
        if delta > 0:
            self._on_bytes(delta)


# ---------------------------------------------------------------------------
# 채널 풀 기반 병렬 실행
# ---------------------------------------------------------------------------
# 파일마다 SFTP 채널을 새로 열면 원격 sshd의 세션 한도(MaxSessions, 기본 10)에
# 부딪혀 ChannelException('Connect failed')이 난다. 따라서 워커 수만큼 채널을
# 한 번만 열어 재사용하고, 각 워커 스레드가 자기 채널로 작업 큐를 비운다.

def _run_with_channel_pool(
    ssh: paramiko.SSHClient,
    work: list[tuple[str, tuple]],
    op: Callable[[paramiko.SFTPClient, tuple], bool],
    max_workers: int,
    on_file: FileCallback | None,
    cancel_event: threading.Event | None,
) -> tuple[int, int]:
    """work의 각 항목을 op(sftp, payload)로 처리한다.

    Args:
        work: [(key, payload), ...] — key는 진행률/로그 표기용.
        op:   (sftp, payload) -> 성공 여부. 채널은 워커가 재사용해 넘겨준다.
    """
    n = max(1, min(max_workers, len(work)))
    channels: list[paramiko.SFTPClient] = []
    for _ in range(n):
        try:
            channels.append(_open_sftp_retry(ssh))
        except Exception as exc:
            logger.warning("SFTP 채널 확보 실패(%d/%d): %s", len(channels), n, exc)
            break
    if not channels:
        # 최소 1개는 필수 — 못 열면 예외를 올려 잡을 error 처리한다.
        channels.append(_open_sftp_retry(ssh))
    logger.info("SFTP 채널 %d개로 %d개 항목 전송", len(channels), len(work))

    work_q: queue.Queue = queue.Queue()
    for item in work:
        work_q.put(item)

    counts = {"success": 0, "failure": 0}
    lock = threading.Lock()

    def worker(sftp: paramiko.SFTPClient) -> None:
        while True:
            if cancel_event and cancel_event.is_set():
                return
            try:
                key, payload = work_q.get_nowait()
            except queue.Empty:
                return
            try:
                ok = bool(op(sftp, payload))
                err = None if ok else "전송 실패"
            except Exception as exc:
                logger.error("전송 실패 (%s): %s", key, exc)
                ok = False
                err = str(exc)
            with lock:
                counts["success" if ok else "failure"] += 1
            if on_file:
                on_file(key, ok, err)

    threads = [threading.Thread(target=worker, args=(c,), daemon=True) for c in channels]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in channels:
        try:
            c.close()
        except Exception:
            pass

    return counts["success"], counts["failure"]


# ---------------------------------------------------------------------------
# 다운로드 (원격 → 로컬)
# ---------------------------------------------------------------------------

def _download_one(
    sftp: paramiko.SFTPClient,
    remote_path: str,
    local_path: str,
    on_bytes: BytesCallback | None,
    cancel_event: threading.Event | None,
) -> bool:
    """주어진 SFTP 채널로 단일 원격 파일을 로컬로 받는다(채널은 재사용)."""
    if cancel_event and cancel_event.is_set():
        return False
    local = Path(local_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    callback = _IncrementalCallback(on_bytes) if on_bytes else None
    sftp.get(remote_path, str(local), callback=callback)
    return True


def download_files(
    ssh: paramiko.SSHClient,
    local_dir: str,
    *,
    remote_dir: str | None = None,
    keys: list[str] | None = None,
    max_workers: int = 4,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """remote_dir(재귀) 또는 keys(파일 목록)를 로컬 디렉터리로 다운로드한다.

    - remote_dir 모드: 하위 구조를 보존하며 local_dir 아래로 받는다.
    - keys 모드: 각 파일을 local_dir/<파일명>으로 받는다(평면).

    Returns:
        (성공 개수, 실패 개수)
    """
    if remote_dir is None and not keys:
        raise ValueError("remote_dir 또는 keys 중 하나를 지정해야 합니다.")

    # (remote_path, local_relative_path) 쌍 수집
    targets: list[tuple[str, str]] = []
    if keys:
        for k in keys:
            targets.append((k, posixpath.basename(k.rstrip("/"))))
    else:
        assert remote_dir is not None
        base = remote_dir.rstrip("/")
        for obj in list_all_files(ssh, base):
            rel = obj["key"][len(base):].lstrip("/")
            targets.append((obj["key"], rel))

    if not targets:
        return 0, 0

    work: list[tuple[str, tuple]] = []
    for remote_path, rel in targets:
        local_path = os.path.join(local_dir, *rel.split("/"))
        work.append((remote_path, (remote_path, local_path)))

    def op(sftp: paramiko.SFTPClient, payload: tuple) -> bool:
        rp, lp = payload
        return _download_one(sftp, rp, lp, on_bytes, cancel_event)

    return _run_with_channel_pool(ssh, work, op, max_workers, on_file, cancel_event)


# ---------------------------------------------------------------------------
# 업로드 (로컬 → 원격)
# ---------------------------------------------------------------------------

def _collect_local_files(local_paths: list[str]) -> list[tuple[Path, Path]]:
    """파일/폴더 혼합 목록에서 (파일 Path, 기준 부모 Path) 쌍을 재귀로 수집한다."""
    result = []
    for raw in local_paths:
        p = Path(raw)
        if p.is_file():
            result.append((p, p.parent))
        elif p.is_dir():
            for sub in p.rglob("*"):
                if sub.is_file():
                    result.append((sub, p.parent))
        else:
            logger.warning("경로를 찾을 수 없음: %s", raw)
    return result


def _sftp_makedirs(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    """원격 디렉터리를 재귀적으로 생성한다(mkdir -p)."""
    parts = remote_dir.strip("/").split("/")
    cur = "/" if remote_dir.startswith("/") else ""
    for part in parts:
        if not part:
            continue
        cur = posixpath.join(cur, part) if cur else part
        try:
            sftp.stat(cur)
        except IOError:
            try:
                sftp.mkdir(cur)
            except IOError:
                pass  # 경쟁 조건으로 이미 생성됐을 수 있음


def _upload_one(
    sftp: paramiko.SFTPClient,
    local_file: Path,
    remote_path: str,
    on_bytes: BytesCallback | None,
    cancel_event: threading.Event | None,
) -> bool:
    """주어진 SFTP 채널로 단일 로컬 파일을 원격에 올린다(채널은 재사용)."""
    if cancel_event and cancel_event.is_set():
        return False
    parent = posixpath.dirname(remote_path)
    if parent:
        _sftp_makedirs(sftp, parent)
    callback = _IncrementalCallback(on_bytes) if on_bytes else None
    sftp.put(str(local_file), remote_path, callback=callback)
    return True


def upload_files(
    ssh: paramiko.SSHClient,
    remote_dir: str,
    local_paths: list[str],
    *,
    max_workers: int = 4,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """로컬 경로 목록(파일/폴더 혼합)을 remote_dir 하위로 업로드한다.

    Returns:
        (성공 개수, 실패 개수)
    """
    file_pairs = _collect_local_files(local_paths)
    if not file_pairs:
        return 0, 0

    remote_base = remote_dir.rstrip("/")
    work: list[tuple[str, tuple]] = []
    for local_file, base_parent in file_pairs:
        rel = local_file.relative_to(base_parent).as_posix()
        remote_path = posixpath.join(remote_base, rel) if remote_base else rel
        work.append((remote_path, (local_file, remote_path)))

    def op(sftp: paramiko.SFTPClient, payload: tuple) -> bool:
        lf, rp = payload
        return _upload_one(sftp, lf, rp, on_bytes, cancel_event)

    return _run_with_channel_pool(ssh, work, op, max_workers, on_file, cancel_event)
