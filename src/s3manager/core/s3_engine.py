"""S3 작업 엔진.

list / tree / download / upload / sync 기능을 콜백 기반으로 제공한다.
기존 S3DownloaderGUI 로직을 확장·재사용한다.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterator

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# 진단: 다운로드/업로드 예외의 전체 트레이스백을 프로세스당 최대 몇 건만 WARNING으로 남긴다.
# per-file 로그는 대량 작업 시 범람하므로 debug로 낮췄지만, 원인 파악을 위해 처음 몇 건은
# 스택까지 보이게 한다(상한이 있어 범람하지 않음).
_DIAG_TRACE_MAX = 3
_diag_trace_count = 0
_diag_lock = threading.Lock()


def _diag_trace(msg: str, key: str, exc: Exception) -> None:
    global _diag_trace_count
    with _diag_lock:
        if _diag_trace_count >= _DIAG_TRACE_MAX:
            return
        _diag_trace_count += 1
    logger.warning("%s (%s): %s", msg, key, exc, exc_info=True)


# 콜백 타입 정의
BytesCallback = Callable[[int], None]          # 전송된 바이트 증분 콜백
FileCallback = Callable[[str, bool, str | None], None]  # (key, success, error_msg)


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

CHUNK = 1024 * 1024  # 다운로드 스트림 읽기 단위(취소 확인 주기이기도 하다)


def _strip_prefix(key: str, prefix: str) -> str:
    """key에서 prefix를 제거하고 앞의 '/'를 벗긴다."""
    if prefix and key.startswith(prefix):
        return key[len(prefix):].lstrip("/")
    return key.lstrip("/")


def _remove_quietly(path: Path) -> None:
    """부분 다운로드(.part) 정리 — 실패해도 무시한다."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 탐색 (list / tree)
# ---------------------------------------------------------------------------

def list_one_level(
    s3_client: boto3.client,
    bucket: str,
    prefix: str = "",
) -> dict[str, list]:
    """delimiter='/'로 한 레벨만 열거한다.

    Returns:
        {
            "folders": [{"key": "...", "name": "...", "isFolder": True}, ...],
            "objects": [{"key": "...", "size": N, "lastModified": "ISO", "isFolder": False}, ...],
        }
    """
    folders = []
    objects = []

    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/")

    for page in pages:
        for cp in page.get("CommonPrefixes") or []:
            folder_key = cp["Prefix"]
            segments = folder_key.rstrip("/").split("/")
            name = segments[-1] if segments else folder_key
            folders.append({"key": folder_key, "name": name, "isFolder": True})

        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if key == prefix:
                # prefix 자체(폴더 마커)는 건너뜀
                continue
            objects.append(
                {
                    "key": key,
                    "size": obj.get("Size", 0),
                    "lastModified": obj["LastModified"].isoformat(),
                    "isFolder": False,
                }
            )

    return {"folders": folders, "objects": objects}


def list_all_objects(
    s3_client: boto3.client,
    bucket: str,
    prefix: str = "",
) -> list[dict]:
    """prefix 하위의 모든 객체를 재귀적으로 열거한다(폴더 마커 제외).

    Returns:
        [{"key": "...", "size": N, "lastModified": "ISO", "isFolder": False}, ...]
    """
    objects = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if key.endswith("/") and obj.get("Size", 0) == 0:
                continue
            objects.append(
                {
                    "key": key,
                    "size": obj.get("Size", 0),
                    "lastModified": obj["LastModified"].isoformat(),
                    "isFolder": False,
                }
            )
    return objects


def flat_summary(
    s3_client: boto3.client,
    bucket: str,
    prefix: str = "",
) -> dict[str, int]:
    """prefix 하위 전체 파일 수와 총 바이트를 반환한다."""
    objs = list_all_objects(s3_client, bucket, prefix)
    return {
        "totalFiles": len(objs),
        "totalBytes": sum(o["size"] for o in objs),
    }


# ---------------------------------------------------------------------------
# 다운로드
# ---------------------------------------------------------------------------

class TransferCanceled(Exception):
    """전송 콜백에서 취소가 감지되면 발생 — 진행 중 파일을 즉시 중단시킨다."""


class _BytesProgressCallback:
    """boto3 Callback 어댑터 — 증분 바이트를 외부 콜백으로 전달하고 취소를 감지한다.

    boto3는 전송 중 이 콜백을 주기적으로 호출하므로, 취소 시 예외를 던지면
    download_file/upload_file이 즉시 중단된다(큰 파일도 중간에 멈춤).
    """

    def __init__(
        self,
        on_bytes: BytesCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._on_bytes = on_bytes
        self._cancel_event = cancel_event

    def __call__(self, bytes_amount: int) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise TransferCanceled()
        if self._on_bytes is not None:
            self._on_bytes(bytes_amount)


def download_single(
    s3_client: boto3.client,
    bucket: str,
    key: str,
    local_path: str,
    on_bytes: BytesCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """단일 S3 키를 로컬 경로로 다운로드한다.

    download_file(s3transfer) 대신 get_object 스트림을 청크 루프로 직접 읽는다.
    s3transfer 는 8MB 초과 파일을 내부 스레드 10개로 분할 전송하는데, 취소를
    진행률 콜백(데이터가 읽힐 때만 호출)으로만 감지할 수 있어 커넥션 풀 대기·
    응답 헤더 대기·소켓 read 블록 구간에서는 취소가 먹지 않았다(안 멈추거나
    read_timeout 까지 지연). 여기서는 청크마다 취소를 확인해 즉시 중단한다.

    임시 파일(.part)에 받고 완료 시에만 교체한다 — 취소·실패가 잘린 파일을
    정상 파일처럼 남기지 않는다.

    Returns:
        성공 여부
    """
    if cancel_event and cancel_event.is_set():
        return False

    local = Path(local_path)
    tmp = local.with_name(local.name + ".part")
    try:
        local.parent.mkdir(parents=True, exist_ok=True)

        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            with open(tmp, "wb") as f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        raise TransferCanceled()
                    chunk = body.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    if on_bytes:
                        on_bytes(len(chunk))
        finally:
            body.close()

        os.replace(tmp, local)
        return True
    except TransferCanceled:
        logger.debug("다운로드 취소됨 (%s)", key)
        _remove_quietly(tmp)
        return False
    except ClientError as exc:
        # per-file — debug 유지(대량 작업 시 수천 건이면 로그 스트림 락에서 서버가 정체됨).
        # 실패는 on_file 콜백으로 UI(실패 목록)에 보고된다.
        logger.debug("다운로드 실패 (%s): %s", key, exc)
        _diag_trace("다운로드 실패", key, exc)
        _remove_quietly(tmp)
        return False
    except Exception as exc:
        logger.debug("다운로드 중 예외 (%s): %s", key, exc)
        _diag_trace("다운로드 중 예외", key, exc)
        _remove_quietly(tmp)
        return False


def download_objects(
    s3_client: boto3.client,
    bucket: str,
    local_dir: str,
    *,
    prefixes: list[str] | None = None,
    keys: list[str] | None = None,
    max_workers: int = 5,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    on_total: "Callable[[int, int], None] | None" = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """여러 prefix(폴더) + keys(파일)를 로컬 디렉터리로 다운로드한다.

    prefixes와 keys 중 하나 이상을 지정해야 한다.
    - 각 폴더는 local_dir/<폴더명>/<하위 구조>로 받는다(여러 폴더 충돌 방지).
    - 각 파일은 local_dir/<파일명>으로 받는다.
    - on_total(count, bytes): 대상 열거 직후 1회 호출(진행률 총량 표시용). 이 열거를
      그대로 다운로드에 재사용하므로 총량 파악을 위한 별도 LIST 요청이 필요 없다.

    Returns:
        (성공 개수, 실패 개수)
    """
    if not prefixes and not keys:
        raise ValueError("prefixes 또는 keys 중 하나를 지정해야 합니다.")

    # 대상 (s3_key, local_relative_path) 수집
    targets: list[tuple[str, str]] = []
    total_bytes = 0
    for prefix in prefixes or []:
        folder = prefix.rstrip("/").split("/")[-1] if prefix.rstrip("/") else ""
        for obj in list_all_objects(s3_client, bucket, prefix):
            stripped = _strip_prefix(obj["key"], prefix)
            rel = f"{folder}/{stripped}" if folder else stripped
            targets.append((obj["key"], rel))
            total_bytes += obj.get("size", 0)
    for k in keys or []:
        targets.append((k, os.path.basename(k.rstrip("/"))))

    if on_total:
        on_total(len(targets), total_bytes)

    if not targets:
        return 0, 0

    success = 0
    failure = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key: dict[Future, str] = {}
        for s3_key, rel_path in targets:
            if cancel_event and cancel_event.is_set():
                break
            local_path = os.path.join(local_dir, rel_path)
            fut = executor.submit(
                download_single,
                s3_client,
                bucket,
                s3_key,
                local_path,
                on_bytes,
                cancel_event,
            )
            future_to_key[fut] = s3_key

        for fut in as_completed(future_to_key):
            # 취소되면 남은 항목을 실패로 집계·보고하지 않는다(수천 건이 '실패'로
            # 기록되는 것 방지). 큐에 남은 작업은 시작 즉시 취소를 보고 곧바로 반환한다.
            if cancel_event and cancel_event.is_set():
                break
            s3_key = future_to_key[fut]
            try:
                ok = fut.result()
            except Exception as exc:
                logger.debug("다운로드 future 예외 (%s): %s", s3_key, exc)  # per-file
                ok = False

            if ok:
                success += 1
                if on_file:
                    on_file(s3_key, True, None)
            else:
                failure += 1
                if on_file:
                    on_file(s3_key, False, "다운로드 실패")

    return success, failure


# ---------------------------------------------------------------------------
# 업로드
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


def upload_single(
    s3_client: boto3.client,
    local_file: Path,
    bucket: str,
    s3_key: str,
    on_bytes: BytesCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """단일 로컬 파일을 S3에 업로드한다.

    Returns:
        성공 여부
    """
    if cancel_event and cancel_event.is_set():
        return False

    try:
        kwargs: dict = {"Filename": str(local_file), "Bucket": bucket, "Key": s3_key}
        if on_bytes or cancel_event:
            kwargs["Callback"] = _BytesProgressCallback(on_bytes, cancel_event)
        s3_client.upload_file(**kwargs)
        return True
    except TransferCanceled:
        logger.debug("업로드 취소됨 (%s)", s3_key)
        return False
    except ClientError as exc:
        logger.debug("업로드 실패 (%s): %s", s3_key, exc)  # per-file — debug (로그 범람 방지)
        return False
    except Exception as exc:
        logger.debug("업로드 중 예외 (%s): %s", s3_key, exc)
        return False


def create_folder(s3_client: boto3.client, bucket: str, key: str) -> None:
    """S3에 빈 폴더(0바이트, key 끝에 '/')를 생성한다."""
    folder_key = key if key.endswith("/") else key + "/"
    s3_client.put_object(Bucket=bucket, Key=folder_key, Body=b"")


def upload_objects(
    s3_client: boto3.client,
    bucket: str,
    prefix: str,
    local_paths: list[str],
    *,
    max_workers: int = 5,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """로컬 경로 목록(파일/폴더 혼합)을 bucket/prefix 하위로 업로드한다.

    Returns:
        (성공 개수, 실패 개수)
    """
    file_pairs = _collect_local_files(local_paths)
    if not file_pairs:
        return 0, 0

    success = 0
    failure = 0
    prefix_stripped = prefix.strip("/")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key: dict[Future, str] = {}
        for local_file, base_parent in file_pairs:
            if cancel_event and cancel_event.is_set():
                break
            rel = local_file.relative_to(base_parent).as_posix()
            s3_key = f"{prefix_stripped}/{rel}" if prefix_stripped else rel
            fut = executor.submit(
                upload_single,
                s3_client,
                local_file,
                bucket,
                s3_key,
                on_bytes,
                cancel_event,
            )
            future_to_key[fut] = s3_key

        for fut in as_completed(future_to_key):
            s3_key = future_to_key[fut]
            try:
                ok = fut.result()
            except Exception as exc:
                logger.debug("업로드 future 예외 (%s): %s", s3_key, exc)  # per-file
                ok = False

            if ok:
                success += 1
                if on_file:
                    on_file(s3_key, True, None)
            else:
                failure += 1
                if on_file:
                    on_file(s3_key, False, "업로드 실패")

    return success, failure
