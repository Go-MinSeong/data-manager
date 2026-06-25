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
import shlex
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
    if password and not key_path:
        # 비밀번호 인증: ssh-agent·기본 키 시도를 끄고 바로 password를 쓴다.
        # (키만 허용하지 않는 서버에서 agent 키를 먼저 시도하다 'Bad authentication type'로
        #  실패하는 것을 방지)
        connect_kwargs["password"] = password
        connect_kwargs["allow_agent"] = False
        connect_kwargs["look_for_keys"] = False
    elif password:
        connect_kwargs["password"] = password

    client.connect(**connect_kwargs)

    # 고지연(WAN) 링크에서 SFTP 처리량을 높이기 위해 채널 윈도우를 키운다.
    # paramiko 기본 2MB → 8MB (이후 open_sftp로 여는 채널이 이 값을 상속).
    # 더 많은 데이터를 in-flight로 두어 대역폭-지연 곱이 큰 링크를 잘 채운다.
    transport = client.get_transport()
    if transport is not None:
        transport.default_window_size = 8 * 1024 * 1024

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


def disk_space(ssh: paramiko.SSHClient, path: str) -> dict[str, int]:
    """원격 path가 속한 파일시스템의 용량/여유(byte)를 df로 계산한다."""
    safe = shlex.quote(path if path else ".")
    cmd = f"df -Pk {safe} 2>/dev/null | tail -1"
    _, stdout, _ = ssh.exec_command(cmd, timeout=15)
    parts = stdout.read().decode("utf-8", "replace").split()
    # df -Pk: Filesystem 1024-blocks Used Available Capacity Mounted-on
    if len(parts) < 4:
        raise OSError("df 출력을 해석할 수 없습니다.")
    total = int(parts[1]) * 1024
    free = int(parts[3]) * 1024
    return {"total": total, "free": free, "used": max(0, total - free)}


def measure_throughput(
    ssh: paramiko.SSHClient, path: str, size_bytes: int = 8 * 1024 * 1024
) -> dict[str, float]:
    """Mac↔원격 SFTP 처리량을 임시 프로브 파일로 측정한다(bytes/sec).

    path 아래에 임시 파일을 쓰고(업로드 속도)·읽고(다운로드 속도) 즉시 삭제한다.
    """
    sftp = _open_sftp_retry(ssh)
    base = (path.rstrip("/") or "/") if path else "."
    probe = posixpath.join(base, f".dm_speedtest_{threading.get_ident()}")
    block = b"\0" * (1024 * 1024)
    try:
        # 업로드
        t0 = time.monotonic()
        with sftp.open(probe, "wb") as wf:
            wf.set_pipelined(True)
            written = 0
            while written < size_bytes:
                wf.write(block)
                written += len(block)
        up_elapsed = max(1e-6, time.monotonic() - t0)
        # 다운로드
        t0 = time.monotonic()
        with sftp.open(probe, "rb") as rf:
            rf.prefetch()
            while rf.read(1024 * 1024):
                pass
        down_elapsed = max(1e-6, time.monotonic() - t0)
        return {
            "uploadBps": size_bytes / up_elapsed,
            "downloadBps": size_bytes / down_elapsed,
            "sizeBytes": size_bytes,
        }
    finally:
        try:
            sftp.remove(probe)
        except Exception:
            pass
        sftp.close()


# ---------------------------------------------------------------------------
# 진행률 콜백 어댑터
# ---------------------------------------------------------------------------

class TransferCanceled(Exception):
    """전송 콜백에서 취소가 감지되면 발생 — 진행 중 파일을 즉시 중단시킨다."""


class _IncrementalCallback:
    """paramiko의 누적(cumulative) 진행 콜백을 증분(delta) 콜백으로 변환하고 취소를 감지한다.

    paramiko get/put 콜백은 파일별로 (transferred, total) 누적값을 전달하므로,
    파일 1건당 인스턴스 1개를 사용해 직전 값과의 차이를 외부 on_bytes로 보낸다.
    전송 중 취소되면 예외를 던져 get/put을 즉시 중단시킨다(큰 파일도 중간에 멈춤).
    """

    def __init__(
        self,
        on_bytes: BytesCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._on_bytes = on_bytes
        self._cancel_event = cancel_event
        self._last = 0

    def __call__(self, transferred: int, total: int) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise TransferCanceled()
        delta = transferred - self._last
        self._last = transferred
        if delta > 0 and self._on_bytes is not None:
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
            except TransferCanceled:
                logger.debug("전송 취소됨 (%s)", key)
                return  # 취소 시 이 워커는 남은 작업을 처리하지 않고 종료
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
    callback = _IncrementalCallback(on_bytes, cancel_event)
    sftp.get(remote_path, str(local), callback=callback)
    return True


def download_files(
    ssh: paramiko.SSHClient,
    local_dir: str,
    *,
    remote_dirs: list[str] | None = None,
    keys: list[str] | None = None,
    max_workers: int = 4,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """여러 원격 폴더(재귀) + 파일을 로컬 디렉터리로 다운로드한다.

    - 각 폴더는 local_dir/<폴더명>/<하위 구조>로 받는다(여러 폴더 충돌 방지).
    - 각 파일은 local_dir/<파일명>으로 받는다.

    Returns:
        (성공 개수, 실패 개수)
    """
    if not remote_dirs and not keys:
        raise ValueError("remote_dirs 또는 keys 중 하나를 지정해야 합니다.")

    # (remote_path, local_relative_path) 쌍 수집
    targets: list[tuple[str, str]] = []
    for remote_dir in remote_dirs or []:
        base = remote_dir.rstrip("/")
        folder = posixpath.basename(base) if base else ""
        for obj in list_all_files(ssh, base):
            stripped = obj["key"][len(base):].lstrip("/")
            rel = f"{folder}/{stripped}" if folder else stripped
            targets.append((obj["key"], rel))
    for k in keys or []:
        targets.append((k, posixpath.basename(k.rstrip("/"))))

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


def read_file_bytes(ssh: paramiko.SSHClient, path: str, max_bytes: int) -> bytes:
    """원격 파일 전체를 읽어 바이트로 반환한다(미리보기용, max_bytes 초과 시 오류)."""
    sftp = _open_sftp_retry(ssh)
    try:
        size = sftp.stat(path).st_size
        if size > max_bytes:
            raise ValueError(f"파일이 너무 큽니다({size}바이트, 최대 {max_bytes})")
        with sftp.open(path, "rb") as f:
            f.prefetch()
            return f.read()
    finally:
        sftp.close()


def make_dir(ssh: paramiko.SSHClient, path: str) -> None:
    """원격에 디렉터리를 생성한다(상위 경로 포함, mkdir -p)."""
    sftp = _open_sftp_retry(ssh)
    try:
        _sftp_makedirs(sftp, path)
    finally:
        sftp.close()


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
    callback = _IncrementalCallback(on_bytes, cancel_event)
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
