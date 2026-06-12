"""S3 작업 엔진.

list / tree / download / upload / sync 기능을 콜백 기반으로 제공한다.
기존 S3DownloaderGUI 로직을 확장·재사용한다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterator

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# 콜백 타입 정의
BytesCallback = Callable[[int], None]          # 전송된 바이트 증분 콜백
FileCallback = Callable[[str, bool, str | None], None]  # (key, success, error_msg)


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _strip_prefix(key: str, prefix: str) -> str:
    """key에서 prefix를 제거하고 앞의 '/'를 벗긴다."""
    if prefix and key.startswith(prefix):
        return key[len(prefix):].lstrip("/")
    return key.lstrip("/")


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
                    "etag": (obj.get("ETag") or "").strip('"'),
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


def _local_md5(path: Path, chunk: int = 1024 * 1024) -> str:
    """로컬 파일의 MD5 해시(hex)를 계산한다. S3 단일파트 ETag와 비교용."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 다운로드
# ---------------------------------------------------------------------------

class _BytesProgressCallback:
    """boto3 Callback 어댑터 — 증분 바이트를 외부 콜백으로 전달한다."""

    def __init__(self, on_bytes: BytesCallback) -> None:
        self._on_bytes = on_bytes

    def __call__(self, bytes_amount: int) -> None:
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

    Returns:
        성공 여부
    """
    if cancel_event and cancel_event.is_set():
        return False

    try:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)

        kwargs: dict = {"Bucket": bucket, "Key": key, "Filename": str(local)}
        if on_bytes:
            kwargs["Callback"] = _BytesProgressCallback(on_bytes)

        s3_client.download_file(**kwargs)
        return True
    except ClientError as exc:
        logger.error("다운로드 실패 (%s): %s", key, exc)
        return False
    except Exception as exc:
        logger.error("다운로드 중 예외 (%s): %s", key, exc)
        return False


def download_objects(
    s3_client: boto3.client,
    bucket: str,
    local_dir: str,
    *,
    prefix: str | None = None,
    keys: list[str] | None = None,
    max_workers: int = 5,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """prefix 또는 keys 목록을 로컬 디렉터리로 다운로드한다.

    prefix와 keys 중 하나는 반드시 지정해야 한다.

    Returns:
        (성공 개수, 실패 개수)
    """
    if prefix is None and not keys:
        raise ValueError("prefix 또는 keys 중 하나를 지정해야 합니다.")

    # 대상 키 목록 수집
    if keys:
        targets = [(k, k) for k in keys]  # (s3_key, relative_path)
    else:
        assert prefix is not None
        objs = list_all_objects(s3_client, bucket, prefix)
        targets = [
            (obj["key"], _strip_prefix(obj["key"], prefix)) for obj in objs
        ]

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
            s3_key = future_to_key[fut]
            try:
                ok = fut.result()
            except Exception as exc:
                logger.error("다운로드 future 예외 (%s): %s", s3_key, exc)
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
        if on_bytes:
            kwargs["Callback"] = _BytesProgressCallback(on_bytes)
        s3_client.upload_file(**kwargs)
        return True
    except ClientError as exc:
        logger.error("업로드 실패 (%s): %s", s3_key, exc)
        return False
    except Exception as exc:
        logger.error("업로드 중 예외 (%s): %s", s3_key, exc)
        return False


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
                logger.error("업로드 future 예외 (%s): %s", s3_key, exc)
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


# ---------------------------------------------------------------------------
# 동기화 (sync)
# ---------------------------------------------------------------------------

def sync_down(
    s3_client: boto3.client,
    bucket: str,
    prefix: str,
    local_dir: str,
    *,
    max_workers: int = 5,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """S3 → 로컬 동기화 (변경분만 다운로드, 삭제 없음).

    크기가 다르거나 S3 LastModified가 로컬보다 최신인 경우에만 다운로드한다.
    ⚠️ 설계상 어떤 파일/객체도 삭제하지 않는다 (S3·로컬 모두).

    Returns:
        (성공 개수, 실패 개수)
    """
    s3_objects = list_all_objects(s3_client, bucket, prefix)
    local_root = Path(local_dir)

    # 다운로드 대상 결정
    to_download: list[tuple[str, str]] = []  # (s3_key, local_abs_path)
    for obj in s3_objects:
        rel = _strip_prefix(obj["key"], prefix)
        local_path = local_root / rel

        if not local_path.exists():
            to_download.append((obj["key"], str(local_path)))
            continue

        # 1) 크기가 다르면 변경된 것
        if local_path.stat().st_size != obj["size"]:
            to_download.append((obj["key"], str(local_path)))
            continue
        # 2) 크기가 같으면 내용 해시(ETag=MD5)로 판별.
        #    mtime은 다운로드/복사 시 갱신돼 신뢰할 수 없으므로 사용하지 않는다.
        #    멀티파트 ETag("...-N")는 단순 MD5가 아니므로 같은 크기는 동일로 간주(재다운로드 방지).
        etag = obj.get("etag", "")
        if etag and "-" not in etag:
            if _local_md5(local_path) != etag:
                to_download.append((obj["key"], str(local_path)))
        # else: 멀티파트 ETag/ETag 없음 → 같은 크기는 동일로 간주(스킵)

    success = 0
    failure = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key: dict[Future, str] = {}
        for s3_key, local_abs in to_download:
            if cancel_event and cancel_event.is_set():
                break
            fut = executor.submit(
                download_single,
                s3_client,
                bucket,
                s3_key,
                local_abs,
                on_bytes,
                cancel_event,
            )
            future_to_key[fut] = s3_key

        for fut in as_completed(future_to_key):
            s3_key = future_to_key[fut]
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if ok:
                success += 1
                if on_file:
                    on_file(s3_key, True, None)
            else:
                failure += 1
                if on_file:
                    on_file(s3_key, False, "다운로드 실패")

    # 삭제 기능 없음: 로컬 전용 파일은 그대로 둔다.
    return success, failure


def sync_up(
    s3_client: boto3.client,
    bucket: str,
    prefix: str,
    local_dir: str,
    *,
    max_workers: int = 5,
    on_bytes: BytesCallback | None = None,
    on_file: FileCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int]:
    """로컬 → S3 동기화 (변경분만 업로드, 삭제 없음).

    크기가 다르거나 로컬 mtime이 S3 LastModified보다 최신인 경우에만 업로드한다.
    ⚠️ 설계상 S3 객체를 절대 삭제하지 않는다. 이 도구에는 어떤 S3 삭제 API도 호출하는
    경로가 존재하지 않는다 (사용 메서드: get_paginator·download_file·upload_file 뿐).

    Returns:
        (성공 개수, 실패 개수)
    """
    local_root = Path(local_dir)
    prefix_stripped = prefix.strip("/")

    # 로컬 파일 목록
    local_files: list[tuple[Path, str]] = []  # (abs_path, s3_key)
    for f in local_root.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(local_root).as_posix()
        s3_key = f"{prefix_stripped}/{rel}" if prefix_stripped else rel
        local_files.append((f, s3_key))

    # S3 현황 조회
    s3_objects = list_all_objects(s3_client, bucket, prefix)
    s3_map: dict[str, dict] = {o["key"]: o for o in s3_objects}

    to_upload: list[tuple[Path, str]] = []
    for local_path, s3_key in local_files:
        if s3_key not in s3_map:
            to_upload.append((local_path, s3_key))
            continue
        s3_obj = s3_map[s3_key]
        # 1) 크기가 다르면 변경된 것
        if local_path.stat().st_size != s3_obj["size"]:
            to_upload.append((local_path, s3_key))
            continue
        # 2) 크기가 같으면 내용 해시(ETag=MD5)로 판별.
        #    다운로드 직후 로컬 mtime이 갱신돼 mtime 비교는 신뢰할 수 없으므로 사용하지 않는다.
        #    멀티파트 업로드 ETag(예: "...-3")는 단순 MD5가 아니므로, 이 경우 같은 크기는
        #    변경 없음으로 간주(불필요한 재업로드 방지).
        etag = s3_obj.get("etag", "")
        if etag and "-" not in etag:
            if _local_md5(local_path) != etag:
                to_upload.append((local_path, s3_key))
        # else: 멀티파트 ETag이거나 ETag 없음 → 같은 크기는 동일로 간주(스킵)

    success = 0
    failure = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key: dict[Future, str] = {}
        for local_path, s3_key in to_upload:
            if cancel_event and cancel_event.is_set():
                break
            fut = executor.submit(
                upload_single,
                s3_client,
                local_path,
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
            except Exception:
                ok = False
            if ok:
                success += 1
                if on_file:
                    on_file(s3_key, True, None)
            else:
                failure += 1
                if on_file:
                    on_file(s3_key, False, "업로드 실패")

    # 삭제 기능 없음: S3 전용 객체는 절대 삭제하지 않는다.
    return success, failure
