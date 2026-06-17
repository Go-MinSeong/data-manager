"""S3 ↔ 원격(SFTP) 전송 엔진.

기본은 **직통**: Mac이 presigned URL을 만들고 원격에서 curl로 S3와 직접 주고받는다.
데이터가 Mac을 거치지 않아 빠르고, 서버에 AWS 자격증명을 두지 않는다.
원격이 S3에 못 닿거나 curl이 없으면 **릴레이**로 폴백 — Mac이 스트리밍 중계한다.

보안: presigned URL은 단일 객체·단일 작업·단기 만료. SSH 암호화 채널로만 전달하며
로그에 URL을 남기지 않는다.
"""

from __future__ import annotations

import logging
import posixpath
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import paramiko

from s3manager.core import s3_engine, sftp_engine
from s3manager.core.s3_engine import TransferCanceled, _BytesProgressCallback

logger = logging.getLogger(__name__)

BytesCallback = Callable[[int], None]
FileCallback = Callable[[str, bool, str | None], None]

CHUNK = 1024 * 1024  # 릴레이 청크 크기
PRESIGN_EXPIRES = 3600  # presigned URL 만료(초)


# ---------------------------------------------------------------------------
# 대상 목록 수집 — (소스 식별자, 상대 경로, 크기)
# 폴더는 <폴더명>/ 하위 보존, 파일은 파일명 (다운로드 규칙과 동일)
# ---------------------------------------------------------------------------

def _enumerate_s3(s3_client, bucket, prefixes, keys) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for prefix in prefixes or []:
        folder = prefix.rstrip("/").split("/")[-1] if prefix.rstrip("/") else ""
        for obj in s3_engine.list_all_objects(s3_client, bucket, prefix):
            stripped = s3_engine._strip_prefix(obj["key"], prefix)
            rel = f"{folder}/{stripped}" if folder else stripped
            out.append((obj["key"], rel, obj.get("size", 0)))
    for k in keys or []:
        out.append((k, posixpath.basename(k.rstrip("/")), 0))
    return out


def _enumerate_remote(ssh, remote_dirs, keys) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for d in remote_dirs or []:
        base = d.rstrip("/")
        folder = posixpath.basename(base) if base else ""
        for obj in sftp_engine.list_all_files(ssh, base):
            stripped = obj["key"][len(base):].lstrip("/")
            rel = f"{folder}/{stripped}" if folder else stripped
            out.append((obj["key"], rel, obj.get("size", 0)))
    for k in keys or []:
        out.append((k, posixpath.basename(k.rstrip("/")), 0))
    return out


def summarize(targets: list[tuple[str, str, int]]) -> dict[str, int]:
    return {"totalFiles": len(targets), "totalBytes": sum(t[2] for t in targets)}


# ---------------------------------------------------------------------------
# 직통(presigned URL + 원격 curl)
# ---------------------------------------------------------------------------

def remote_can_reach_s3(ssh: paramiko.SSHClient, region: str | None) -> bool:
    """원격에 curl이 있고 S3 엔드포인트에 직접 닿는지 사전 점검."""
    endpoint = f"s3.{region}.amazonaws.com" if region else "s3.amazonaws.com"
    cmd = (
        'command -v curl >/dev/null 2>&1 && '
        f'curl -s -o /dev/null -w "%{{http_code}}" --connect-timeout 8 https://{endpoint} '
        '|| echo NO'
    )
    try:
        _, stdout, _ = ssh.exec_command(cmd, timeout=20)
        res = stdout.read().decode("utf-8", "replace").strip()
        return res.isdigit() and res != "000"
    except Exception as exc:
        logger.debug("S3 도달성 점검 실패: %s", exc)
        return False


def _exec_status(ssh: paramiko.SSHClient, cmd: str) -> tuple[int, str]:
    """원격 명령을 실행하고 (exit_status, stderr)를 반환한다(전송은 timeout 미설정)."""
    _, stdout, stderr = ssh.exec_command(cmd)
    status = stdout.channel.recv_exit_status()
    err = stderr.read().decode("utf-8", "replace").strip()
    return status, err


def _direct_download(ssh, url: str, remote_path: str) -> tuple[bool, str]:
    parent = posixpath.dirname(remote_path)
    mk = f"mkdir -p {shlex.quote(parent)} && " if parent else ""
    cmd = f"{mk}curl -fsS --max-time 86400 -o {shlex.quote(remote_path)} {shlex.quote(url)}"
    status, err = _exec_status(ssh, cmd)
    return status == 0, err


def _direct_upload(ssh, url: str, remote_path: str) -> tuple[bool, str]:
    cmd = f"curl -fsS --max-time 86400 -X PUT -T {shlex.quote(remote_path)} {shlex.quote(url)}"
    status, err = _exec_status(ssh, cmd)
    return status == 0, err


# ---------------------------------------------------------------------------
# 릴레이(Mac 스트리밍 중계)
# ---------------------------------------------------------------------------

def _relay_download(s3_client, sftp, bucket, key, remote_path, on_bytes, cancel_event):
    """S3 객체를 스트리밍으로 읽어 원격에 기록(로컬 디스크 미경유)."""
    parent = posixpath.dirname(remote_path)
    if parent:
        sftp_engine._sftp_makedirs(sftp, parent)
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"]
    try:
        with sftp.open(remote_path, "wb") as wf:
            wf.set_pipelined(True)
            while True:
                if cancel_event and cancel_event.is_set():
                    raise TransferCanceled()
                chunk = body.read(CHUNK)
                if not chunk:
                    break
                wf.write(chunk)
                if on_bytes:
                    on_bytes(len(chunk))
    finally:
        body.close()


def _relay_upload(s3_client, sftp, remote_path, bucket, key, on_bytes, cancel_event):
    """원격 파일을 스트리밍으로 읽어 S3에 업로드(로컬 디스크 미경유)."""
    with sftp.open(remote_path, "rb") as rf:
        rf.prefetch()
        callback = _BytesProgressCallback(on_bytes, cancel_event)
        s3_client.upload_fileobj(rf, bucket, key, Callback=callback)


# ---------------------------------------------------------------------------
# 공통 실행기 — 직통 우선, 실패 시 파일 단위 릴레이 폴백
# ---------------------------------------------------------------------------

def _run(
    ssh,
    targets: list[tuple[str, str, int]],
    direct_fn,                       # (label) -> (ok, err)  직통 1건
    relay_fn,                        # (sftp, label) -> None  릴레이 1건(예외 시 실패)
    *,
    use_direct: bool,
    max_workers: int,
    on_file: FileCallback | None,
    cancel_event: threading.Event | None,
) -> tuple[int, int]:
    """targets를 직통/릴레이로 처리한다. 직통 실패 건은 일회용 채널로 릴레이 폴백."""
    success = 0
    failure = 0
    lock = threading.Lock()

    def worker(item):
        label = item[0]
        if cancel_event and cancel_event.is_set():
            return label, False, "취소됨"
        # 1) 직통 시도
        if use_direct:
            try:
                ok, err = direct_fn(item)
                if ok:
                    return label, True, None
                logger.warning("직통 실패(%s) → 릴레이 폴백: %s", label, err)
            except Exception as exc:
                logger.warning("직통 예외(%s) → 릴레이 폴백: %s", label, exc)
        # 2) 릴레이 (직통 미사용이거나 직통 실패 시)
        sftp = None
        try:
            sftp = sftp_engine._open_sftp_retry(ssh)
            relay_fn(sftp, item)
            return label, True, None
        except TransferCanceled:
            return label, False, "취소됨"
        except Exception as exc:
            logger.error("전송 실패(%s): %s", label, exc)
            return label, False, str(exc)
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass

    n = max(1, min(max_workers, len(targets)))
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="xfer") as ex:
        futs = [ex.submit(worker, t) for t in targets]
        for fut in as_completed(futs):
            label, ok, err = fut.result()
            with lock:
                if ok:
                    success += 1
                else:
                    failure += 1
            if on_file:
                on_file(label, ok, err)

    return success, failure


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def s3_to_remote(
    s3_client,
    ssh,
    bucket: str,
    *,
    prefixes: list[str] | None = None,
    keys: list[str] | None = None,
    remote_dir: str,
    max_workers: int = 4,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """S3의 여러 폴더/파일을 원격 디렉터리로 복사한다(직통 우선)."""
    targets = _enumerate_s3(s3_client, bucket, prefixes, keys)
    if not targets:
        return 0, 0
    region = getattr(s3_client.meta, "region_name", None)
    use_direct = remote_can_reach_s3(ssh, region)
    logger.info("S3→원격: %d개, 모드=%s", len(targets), "직통" if use_direct else "릴레이")
    base = remote_dir.rstrip("/")

    def _remote_path(rel: str) -> str:
        return f"{base}/{rel}" if base else rel

    def direct_fn(item):
        key, rel, size = item
        url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=PRESIGN_EXPIRES
        )
        ok, err = _direct_download(ssh, url, _remote_path(rel))
        if ok and on_bytes:
            on_bytes(size)  # 직통은 파일 단위 진행
        return ok, err

    def relay_fn(sftp, item):
        key, rel, _ = item
        _relay_download(s3_client, sftp, bucket, key, _remote_path(rel), on_bytes, cancel_event)

    return _run(
        ssh, targets, direct_fn, relay_fn,
        use_direct=use_direct, max_workers=max_workers,
        on_file=on_file, cancel_event=cancel_event,
    )


def remote_to_s3(
    ssh,
    s3_client,
    bucket: str,
    *,
    remote_dirs: list[str] | None = None,
    keys: list[str] | None = None,
    prefix: str = "",
    max_workers: int = 4,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """원격의 여러 폴더/파일을 S3 bucket/prefix로 복사한다(직통 우선)."""
    targets = _enumerate_remote(ssh, remote_dirs, keys)
    if not targets:
        return 0, 0
    region = getattr(s3_client.meta, "region_name", None)
    use_direct = remote_can_reach_s3(ssh, region)
    logger.info("원격→S3: %d개, 모드=%s", len(targets), "직통" if use_direct else "릴레이")
    pfx = prefix.strip("/")

    def _s3_key(rel: str) -> str:
        return f"{pfx}/{rel}" if pfx else rel

    def direct_fn(item):
        remote_path, rel, size = item
        url = s3_client.generate_presigned_url(
            "put_object", Params={"Bucket": bucket, "Key": _s3_key(rel)}, ExpiresIn=PRESIGN_EXPIRES
        )
        ok, err = _direct_upload(ssh, url, remote_path)
        if ok and on_bytes:
            on_bytes(size)
        return ok, err

    def relay_fn(sftp, item):
        remote_path, rel, _ = item
        _relay_upload(s3_client, sftp, remote_path, bucket, _s3_key(rel), on_bytes, cancel_event)

    return _run(
        ssh, targets, direct_fn, relay_fn,
        use_direct=use_direct, max_workers=max_workers,
        on_file=on_file, cancel_event=cancel_event,
    )
