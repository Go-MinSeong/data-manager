"""Pydantic 요청/응답 모델.

계약서 §1에 정의된 데이터 모델을 구현한다.
camelCase 직렬화를 위해 alias_generator를 사용한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """camelCase alias를 자동 생성하는 베이스 모델."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# 자격증명 / 연결
# ---------------------------------------------------------------------------

class Profile(CamelModel):
    """자격증명 프로파일 (비밀키 미포함)."""

    name: str
    source: Literal["aws", "keychain"]
    region: str | None = None


class ProfilesResponse(CamelModel):
    profiles: list[Profile]


class SaveCredentialsRequest(CamelModel):
    """Keychain에 저장할 자격증명."""

    name: str
    access_key_id: str
    secret_access_key: str
    region: str | None = None


class OkResponse(CamelModel):
    ok: bool = True


class ConnectKeysRequest(CamelModel):
    """직접 키로 연결."""

    mode: Literal["keys"]
    access_key_id: str
    secret_access_key: str
    region: str | None = None


class ConnectProfileRequest(CamelModel):
    """프로파일로 연결."""

    mode: Literal["profile"]
    profile_name: str
    region: str | None = None


class ConnectSuccessResponse(CamelModel):
    ok: bool = True
    identity: dict[str, str]
    region: str | None = None


class ConnectErrorResponse(CamelModel):
    ok: bool = False
    error: str


class ConnectionStatusResponse(CamelModel):
    connected: bool
    identity: dict[str, str] | None = None
    region: str | None = None


# ---------------------------------------------------------------------------
# 탐색
# ---------------------------------------------------------------------------

class BucketInfo(CamelModel):
    name: str
    region: str | None = None


class BucketsResponse(CamelModel):
    buckets: list[BucketInfo]


class S3Object(CamelModel):
    key: str
    size: int
    last_modified: str
    is_folder: Literal[False] = False


class S3Folder(CamelModel):
    key: str
    name: str
    is_folder: Literal[True] = True


class ObjectsResponse(CamelModel):
    prefix: str
    folders: list[S3Folder]
    objects: list[S3Object]


class FlatSummaryResponse(CamelModel):
    total_files: int
    total_bytes: int


# ---------------------------------------------------------------------------
# 전송 작업
# ---------------------------------------------------------------------------

class DownloadRequest(CamelModel):
    bucket: str
    prefixes: list[str] | None = None
    keys: list[str] | None = None
    local_dir: str
    max_workers: int = 5


class UploadRequest(CamelModel):
    bucket: str
    prefix: str = ""
    local_paths: list[str]
    max_workers: int = 5


class S3FolderRequest(CamelModel):
    """S3 빈 폴더 생성 요청 — key는 폴더 경로(끝 '/'는 자동 보정)."""

    bucket: str
    key: str


class RemoteFolderRequest(CamelModel):
    """원격 디렉터리 생성 요청."""

    path: str


class JobIdResponse(CamelModel):
    job_id: str


class Job(CamelModel):
    """잡 상태 응답 모델."""

    job_id: str
    kind: str
    local_dir: str = ""
    status: str
    total_files: int
    completed_files: int
    failed_files: int
    total_bytes: int
    transferred_bytes: int
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class JobsResponse(CamelModel):
    jobs: list[Job]


# ---------------------------------------------------------------------------
# 원격(SFTP) 서버
# ---------------------------------------------------------------------------

class RemoteProfile(CamelModel):
    """원격 서버 프로파일 (비밀 미포함)."""

    name: str
    host: str
    port: int = 22
    username: str
    auth_type: Literal["key", "password"] = "key"
    key_path: str | None = None
    default_path: str | None = None


class RemoteProfilesResponse(CamelModel):
    profiles: list[RemoteProfile]


class ProfileHealth(CamelModel):
    """프로파일 도달성 점검 결과(TCP 연결 기준)."""

    name: str
    reachable: bool
    latency_ms: int | None = None


class ProfileHealthResponse(CamelModel):
    results: list[ProfileHealth]


class SaveRemoteProfileRequest(CamelModel):
    """원격 프로파일 저장 요청.

    secret(키 passphrase 또는 password)은 Keychain에만 저장된다.
    """

    name: str
    host: str
    port: int = 22
    username: str
    auth_type: Literal["key", "password"] = "key"
    key_path: str | None = None
    secret: str | None = None


class RemoteConnectionStatusResponse(CamelModel):
    connected: bool
    host: str | None = None
    username: str | None = None
    home_dir: str | None = None
    default_path: str | None = None
    profile_name: str | None = None


class DiskSpaceResponse(CamelModel):
    total: int
    free: int
    used: int


class MeasureResponse(CamelModel):
    upload_bps: float
    download_bps: float
    size_bytes: int


class SetDefaultPathRequest(CamelModel):
    path: str | None = None


class LocalFlatRequest(CamelModel):
    paths: list[str] = []


class RemoteDownloadRequest(CamelModel):
    remote_dirs: list[str] | None = None
    keys: list[str] | None = None
    local_dir: str
    max_workers: int = 4


class RemoteUploadRequest(CamelModel):
    remote_dir: str = ""
    local_paths: list[str]
    max_workers: int = 4


class S3ToRemoteRequest(CamelModel):
    """S3 → 원격 전송."""

    bucket: str
    prefixes: list[str] | None = None
    keys: list[str] | None = None
    remote_dir: str
    max_workers: int = 4


class RemoteToS3Request(CamelModel):
    """원격 → S3 전송."""

    remote_dirs: list[str] | None = None
    keys: list[str] | None = None
    bucket: str
    prefix: str = ""
    max_workers: int = 4


class RemoteToRemoteRequest(CamelModel):
    """원격(소스) → 원격B(대상) 전송. Mac 경유 릴레이."""

    src_dirs: list[str] | None = None
    src_keys: list[str] | None = None
    dest_dir: str
    max_workers: int = 4


# ---------------------------------------------------------------------------
# 로컬 / 시스템
# ---------------------------------------------------------------------------

class RevealRequest(CamelModel):
    path: str


class PickFolderResponse(CamelModel):
    path: str | None = None


class PickFilesResponse(CamelModel):
    paths: list[str]


class HealthResponse(CamelModel):
    ok: bool = True
    version: str


# ---------------------------------------------------------------------------
# 환경설정 (UI 영속 설정)
# ---------------------------------------------------------------------------

class PreferencesResponse(CamelModel):
    hidden_buckets: list[str] = []
    last_download_dir: str = ""


class HiddenBucketsRequest(CamelModel):
    hidden_buckets: list[str] = []
