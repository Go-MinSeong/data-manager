"""FastAPI 앱.

API 계약서의 모든 REST(§2), WebSocket(§3), 정적 서빙(§4)을 구현한다.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any, Protocol, Union

import boto3
import paramiko
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from s3manager import __version__, settings
from s3manager.core import credentials as creds_module
from s3manager.core import preferences as prefs_module
from s3manager.core import remote_profiles as remote_module
from s3manager.core import s3_engine
from s3manager.core import sftp_engine
from s3manager.core.jobs import job_manager
from s3manager.server.models import (
    BucketInfo,
    BucketsResponse,
    CamelModel,
    ConnectErrorResponse,
    ConnectSuccessResponse,
    ConnectionStatusResponse,
    DownloadRequest,
    FlatSummaryResponse,
    HealthResponse,
    HiddenBucketsRequest,
    Job,
    JobIdResponse,
    JobsResponse,
    ObjectsResponse,
    OkResponse,
    PreferencesResponse,
    PickFilesResponse,
    PickFolderResponse,
    Profile,
    ProfilesResponse,
    DiskSpaceResponse,
    MeasureResponse,
    ProfileHealth,
    ProfileHealthResponse,
    RemoteConnectionStatusResponse,
    RemoteDownloadRequest,
    RemoteProfile,
    RemoteProfilesResponse,
    LocalFlatRequest,
    RemoteFolderRequest,
    RemoteToRemoteRequest,
    RemoteToS3Request,
    RemoteUploadRequest,
    S3FolderRequest,
    S3ToRemoteRequest,
    SetDefaultPathRequest,
    RevealRequest,
    S3Folder,
    S3Object,
    SaveCredentialsRequest,
    SaveRemoteProfileRequest,
    UploadRequest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Native bridge 프로토콜 및 주입
# ---------------------------------------------------------------------------

class NativeBridge(Protocol):
    """pywebview 셸이 구현하는 네이티브 다이얼로그 인터페이스."""

    def pick_folder(self) -> str | None:
        ...

    def pick_files(self) -> list[str]:
        ...

    def reveal(self, path: str) -> None:
        ...


_native_bridge: NativeBridge | None = None


def set_native_bridge(bridge: NativeBridge) -> None:
    """셸이 앱 시작 시 네이티브 브릿지를 주입한다."""
    global _native_bridge
    _native_bridge = bridge
    logger.info("네이티브 브릿지 주입 완료: %s", type(bridge).__name__)


# ---------------------------------------------------------------------------
# 활성 세션 (싱글톤)
# ---------------------------------------------------------------------------

class _ActiveSession:
    """서버 메모리에 보관되는 활성 boto3 세션."""

    def __init__(self) -> None:
        self.session: boto3.Session | None = None
        self.client: boto3.client | None = None
        self.identity: dict[str, str] | None = None
        self.region: str | None = None
        self.connected: bool = False

    def connect(
        self,
        session: boto3.Session,
        client: boto3.client,
        identity: dict[str, str],
        region: str | None,
    ) -> None:
        self.session = session
        self.client = client
        self.identity = identity
        self.region = region
        self.connected = True

    def disconnect(self) -> None:
        self.session = None
        self.client = None
        self.identity = None
        self.region = None
        self.connected = False

    def require_client(self) -> boto3.client:
        """클라이언트를 반환하거나, 연결 안 됐으면 409를 raise한다."""
        if not self.connected or self.client is None:
            raise HTTPException(status_code=409, detail="S3에 연결되어 있지 않습니다. 먼저 /api/connect를 호출하세요.")
        return self.client


_session = _ActiveSession()


class _RemoteSession:
    """서버 메모리에 보관되는 활성 SFTP(SSH) 연결. S3 세션과 독립적."""

    def __init__(self) -> None:
        self.ssh = None  # paramiko.SSHClient | None
        self.host: str | None = None
        self.username: str | None = None
        self.home_dir: str | None = None
        self.default_path: str | None = None
        self.profile_name: str | None = None
        self.connected: bool = False

    def connect(
        self,
        ssh,
        host: str,
        username: str,
        home_dir: str,
        *,
        default_path: str | None = None,
        profile_name: str | None = None,
    ) -> None:
        # 기존 연결이 있으면 정리
        self.disconnect()
        self.ssh = ssh
        self.host = host
        self.username = username
        self.home_dir = home_dir
        self.default_path = default_path
        self.profile_name = profile_name
        self.connected = True

    def disconnect(self) -> None:
        if self.ssh is not None:
            try:
                self.ssh.close()
            except Exception:
                pass
        self.ssh = None
        self.host = None
        self.username = None
        self.home_dir = None
        self.default_path = None
        self.profile_name = None
        self.connected = False

    def require_ssh(self):
        """SSH 클라이언트를 반환한다. 연결 안 됨/끊김이면 409를 raise하고 세션을 정리한다."""
        if not self.connected or self.ssh is None:
            raise HTTPException(
                status_code=409,
                detail="원격 서버에 연결되어 있지 않습니다. 먼저 연결하세요.",
            )
        # transport가 죽었으면(연결 끊김) 세션을 정리하고 재연결을 유도한다.
        transport = self.ssh.get_transport()
        if transport is None or not transport.is_active():
            self.disconnect()
            raise HTTPException(
                status_code=409,
                detail="원격 서버 연결이 끊겼습니다. 다시 연결하세요.",
            )
        return self.ssh


_remote = _RemoteSession()
# 두 번째 원격 세션 — 원격↔원격 전송의 '대상' 서버용
_remote_b = _RemoteSession()


def _connect_into(session: "_RemoteSession", body: dict) -> JSONResponse:
    """body(profile/adhoc)로 SSH 연결을 맺어 주어진 세션에 저장한다."""
    mode = body.get("mode")
    if mode not in ("profile", "adhoc"):
        raise HTTPException(status_code=422, detail="mode는 'profile' 또는 'adhoc'이어야 합니다.")

    if mode == "profile":
        name = body.get("profileName")
        if not name:
            raise HTTPException(status_code=422, detail="profile 모드에는 profileName이 필요합니다.")
        prof = remote_module.load_remote_profile(name)
        if prof is None:
            raise HTTPException(status_code=404, detail=f"원격 프로파일을 찾을 수 없습니다: {name}")
        host, port, username = prof["host"], prof["port"], prof["username"]
        auth_type, key_path, secret = prof["authType"], prof.get("keyPath"), prof.get("secret")
        default_path = prof.get("defaultPath")
        profile_name = name
    else:
        host = body.get("host")
        username = body.get("username")
        if not host or not username:
            raise HTTPException(status_code=422, detail="adhoc 모드에는 host와 username이 필요합니다.")
        port = int(body.get("port") or 22)
        auth_type = body.get("authType") or "key"
        key_path = body.get("keyPath")
        secret = body.get("secret")
        default_path = None
        profile_name = None

    key_passphrase = secret if auth_type == "key" else None
    password = secret if auth_type == "password" else None

    try:
        ssh = sftp_engine.connect(
            host=host, port=port, username=username,
            key_path=key_path, key_passphrase=key_passphrase, password=password,
        )
        home = sftp_engine.home_dir(ssh)
    except Exception as exc:
        logger.warning("원격 연결 실패: %s", exc)
        return JSONResponse(status_code=200, content={"ok": False, "error": str(exc)})

    session.connect(
        ssh, host=host, username=username, home_dir=home,
        default_path=default_path, profile_name=profile_name,
    )
    logger.info("원격 연결 성공: %s@%s (home=%s)", username, host, home)
    return JSONResponse(
        content={
            "ok": True, "host": host, "username": username, "homeDir": home,
            "defaultPath": default_path, "profileName": profile_name,
        }
    )

# ---------------------------------------------------------------------------
# FastAPI 앱 생성
# ---------------------------------------------------------------------------

app = FastAPI(title="Data Manager API", version=__version__)


# ---------------------------------------------------------------------------
# 로컬 접근 인증 (§ 보안)
# ---------------------------------------------------------------------------
# 같은 Mac의 다른 사용자/프로세스/브라우저가 127.0.0.1:8765 에 접근하는 것을 막는다.
# 셸(pywebview)이 실행마다 무작위 토큰을 발급해 set_auth_token()으로 등록하고,
# 창 URL(?t=)로만 토큰을 전달한다. 토큰을 모르는 호출은 /api/* 에서 401.
# 토큰이 등록되지 않은 경우(=순수 개발 모드: npm run dev + uvicorn) 인증을 건너뛴다.

_auth_token: str | None = None

# DNS 리바인딩 방지를 위해 허용하는 Host 헤더 값
_ALLOWED_HOSTS = {
    f"{settings.HOST}:{settings.PORT}",
    f"127.0.0.1:{settings.PORT}",
    f"localhost:{settings.PORT}",
}

# 인증 없이 허용하는 경로 (셸 health 폴링 + 정적/SPA)
_AUTH_EXEMPT_PREFIXES = ("/api/health",)


def set_auth_token(token: str) -> None:
    """셸이 발급한 로컬 접근 토큰을 등록한다."""
    global _auth_token
    _auth_token = token
    logger.info("로컬 접근 토큰 등록 완료 (인증 활성화)")


def _is_token_valid(token: str | None) -> bool:
    """등록된 토큰과 일치하는지 검사. 미등록 시(개발 모드) 항상 통과."""
    if _auth_token is None:
        return True
    return bool(token) and token == _auth_token


@app.middleware("http")
async def _security_middleware(request, call_next):
    """Host 검증 + /api/* 토큰 검증."""
    # 1) Host 헤더 검증 (DNS 리바인딩 방지)
    host = request.headers.get("host", "")
    if host and host not in _ALLOWED_HOSTS:
        return JSONResponse(status_code=400, content={"detail": "허용되지 않은 Host"})

    # 2) /api/* 토큰 검증 (health·정적 경로는 면제)
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(_AUTH_EXEMPT_PREFIXES):
        token = request.headers.get("x-s3m-token") or request.query_params.get("t")
        if not _is_token_valid(token):
            return JSONResponse(status_code=401, content={"detail": "인증 실패"})

    return await call_next(request)


@app.on_event("startup")
async def _startup() -> None:
    """앱 시작 시 asyncio 루프를 잡 매니저에 주입한다."""
    loop = asyncio.get_running_loop()
    job_manager.set_event_loop(loop)
    logger.info("Data Manager 백엔드 시작 (포트 %s)", settings.PORT)


# ---------------------------------------------------------------------------
# 헬스체크
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """서버 상태 확인."""
    return HealthResponse(ok=True, version=__version__)


# ---------------------------------------------------------------------------
# 환경설정 (숨긴 버킷 등 UI 영속 설정)
# ---------------------------------------------------------------------------

@app.get("/api/preferences", response_model=PreferencesResponse)
async def get_preferences() -> PreferencesResponse:
    """저장된 환경설정을 반환한다."""
    return PreferencesResponse(
        hidden_buckets=prefs_module.get_hidden_buckets(),
        last_download_dir=prefs_module.get_last_download_dir(),
    )


@app.put("/api/preferences/hidden-buckets", response_model=PreferencesResponse)
async def put_hidden_buckets(body: HiddenBucketsRequest) -> PreferencesResponse:
    """숨긴 버킷 목록을 저장한다."""
    cleaned = prefs_module.set_hidden_buckets(body.hidden_buckets)
    return PreferencesResponse(hidden_buckets=cleaned)


# ---------------------------------------------------------------------------
# 자격증명 / 연결
# ---------------------------------------------------------------------------

@app.get("/api/profiles", response_model=ProfilesResponse)
async def get_profiles() -> ProfilesResponse:
    """~/.aws 와 Keychain의 프로파일을 합쳐 반환한다."""
    raw = creds_module.list_all_profiles()
    profiles = [
        Profile(
            name=p["name"],
            source=p["source"],  # type: ignore[arg-type]
            region=p.get("region"),
        )
        for p in raw
    ]
    return ProfilesResponse(profiles=profiles)


@app.post("/api/credentials", response_model=OkResponse)
async def save_credentials(body: SaveCredentialsRequest) -> OkResponse:
    """자격증명을 Keychain에 저장한다."""
    creds_module.save_keychain_profile(
        name=body.name,
        access_key_id=body.access_key_id,
        secret_access_key=body.secret_access_key,
        region=body.region,
    )
    creds_module.register_keychain_profile_name(body.name)
    return OkResponse(ok=True)


@app.delete("/api/credentials/{name}", response_model=OkResponse)
async def delete_credentials(name: str) -> OkResponse:
    """Keychain에서 프로파일을 삭제한다."""
    creds_module.delete_keychain_profile(name)
    creds_module.unregister_keychain_profile_name(name)
    return OkResponse(ok=True)


@app.post("/api/connect")
def connect(body: dict) -> JSONResponse:
    """자격증명 검증 후 활성 세션을 서버 메모리에 저장한다.

    body:
      - { mode: "keys", accessKeyId, secretAccessKey, region }
      - { mode: "profile", profileName, region? }
    """
    mode = body.get("mode")
    if mode not in ("keys", "profile"):
        raise HTTPException(status_code=422, detail="mode는 'keys' 또는 'profile'이어야 합니다.")

    try:
        boto_session, identity = creds_module.build_session_for_connect(
            mode=mode,
            access_key_id=body.get("accessKeyId"),
            secret_access_key=body.get("secretAccessKey"),
            region=body.get("region"),
            profile_name=body.get("profileName"),
        )
    except Exception as exc:
        logger.warning("연결 실패: %s", exc)
        return JSONResponse(
            status_code=200,
            content={"ok": False, "error": str(exc)},
        )

    # 실제 사용할 리전 결정
    region = body.get("region") or boto_session.region_name or settings.DEFAULT_REGION

    # S3 클라이언트 생성 (이후 모든 버킷 작업에 사용)
    s3_client = boto_session.client("s3", region_name=region)
    _session.connect(
        session=boto_session,
        client=s3_client,
        identity=identity,
        region=region,
    )
    logger.info("S3 연결 성공: account=%s, region=%s", identity.get("account"), region)

    return JSONResponse(
        content={
            "ok": True,
            "identity": {"account": identity["account"], "arn": identity["arn"]},
            "region": region,
        }
    )


@app.get("/api/connection", response_model=ConnectionStatusResponse)
async def get_connection() -> ConnectionStatusResponse:
    """현재 활성 연결 상태를 반환한다."""
    if not _session.connected:
        return ConnectionStatusResponse(connected=False)
    return ConnectionStatusResponse(
        connected=True,
        identity=_session.identity,
        region=_session.region,
    )


@app.post("/api/disconnect", response_model=OkResponse)
async def disconnect() -> OkResponse:
    """S3 활성 세션을 해제한다(다른 프로파일로 전환 시 사용)."""
    _session.disconnect()
    return OkResponse(ok=True)


# ---------------------------------------------------------------------------
# 탐색
# ---------------------------------------------------------------------------

@app.get("/api/buckets", response_model=BucketsResponse)
def list_buckets() -> BucketsResponse:
    """버킷 목록을 반환한다."""
    client = _session.require_client()
    try:
        resp = client.list_buckets()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"버킷 목록 조회 실패: {exc}")

    buckets = []
    for b in resp.get("Buckets", []):
        # get_bucket_location은 추가 API 호출이 필요하므로 best-effort
        region = None
        try:
            loc_resp = client.get_bucket_location(Bucket=b["Name"])
            region = loc_resp.get("LocationConstraint")
        except Exception:
            pass
        buckets.append(BucketInfo(name=b["Name"], region=region))

    return BucketsResponse(buckets=buckets)


@app.get("/api/objects/flat", response_model=FlatSummaryResponse)
def objects_flat(bucket: str, prefix: str = "") -> FlatSummaryResponse:
    """prefix 하위 전체 파일 수와 총 바이트를 반환한다."""
    client = _session.require_client()
    try:
        summary = s3_engine.flat_summary(client, bucket, prefix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"flat 목록 조회 실패: {exc}")
    return FlatSummaryResponse(
        total_files=summary["totalFiles"],
        total_bytes=summary["totalBytes"],
    )


@app.get("/api/objects", response_model=ObjectsResponse)
def list_objects(bucket: str, prefix: str = "") -> ObjectsResponse:
    """delimiter='/'로 한 레벨만 열거한다."""
    client = _session.require_client()
    try:
        result = s3_engine.list_one_level(client, bucket, prefix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"오브젝트 목록 조회 실패: {exc}")

    folders = [S3Folder(**f) for f in result["folders"]]
    objects = [
        S3Object(
            key=o["key"],
            size=o["size"],
            last_modified=o["lastModified"],
        )
        for o in result["objects"]
    ]
    return ObjectsResponse(prefix=prefix, folders=folders, objects=objects)


@app.post("/api/objects/folder", response_model=OkResponse)
def create_s3_folder(body: S3FolderRequest) -> OkResponse:
    """S3에 빈 폴더(0바이트 키, 끝 '/')를 생성한다."""
    client = _session.require_client()
    if not body.key.strip("/"):
        raise HTTPException(status_code=422, detail="폴더 이름이 비어 있습니다.")
    try:
        s3_engine.create_folder(client, body.bucket, body.key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"폴더 생성 실패: {exc}")
    return OkResponse(ok=True)


# ---------------------------------------------------------------------------
# 전송 작업
# ---------------------------------------------------------------------------

@app.post("/api/download", response_model=JobIdResponse)
async def start_download(body: DownloadRequest) -> JobIdResponse:
    """다운로드 잡을 생성한다. prefixes 또는 keys 중 하나 필수."""
    if not body.prefixes and not body.keys:
        raise HTTPException(status_code=422, detail="prefixes 또는 keys 중 하나가 필요합니다.")
    client = _session.require_client()
    # 이 경로를 "마지막 사용 다운로드 경로"로 저장 → 다음 실행 시 기본값으로 사용
    prefs_module.set_last_download_dir(body.local_dir)
    job_id = job_manager.submit_download(
        client,
        body.bucket,
        body.local_dir,
        prefixes=body.prefixes,
        keys=body.keys,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


@app.post("/api/upload", response_model=JobIdResponse)
async def start_upload(body: UploadRequest) -> JobIdResponse:
    """업로드 잡을 생성한다."""
    client = _session.require_client()
    job_id = job_manager.submit_upload(
        client,
        body.bucket,
        body.prefix,
        body.local_paths,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


@app.get("/api/jobs", response_model=JobsResponse)
async def list_jobs() -> JobsResponse:
    """최근 잡 이력을 최신순으로 반환한다."""
    jobs = [
        Job(**j.to_dict())
        for j in job_manager.list_jobs()
    ]
    return JobsResponse(jobs=jobs)


@app.get("/api/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str) -> Job:
    """잡 단건 조회."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"잡을 찾을 수 없습니다: {job_id}")
    return Job(**job.to_dict())


@app.post("/api/jobs/{job_id}/cancel", response_model=OkResponse)
async def cancel_job(job_id: str) -> OkResponse:
    """잡 취소 요청."""
    ok = job_manager.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"잡을 찾을 수 없거나 이미 완료됨: {job_id}")
    return OkResponse(ok=True)


# ---------------------------------------------------------------------------
# 원격(SFTP) 서버 — 프로파일 / 연결 / 탐색 / 전송
# ---------------------------------------------------------------------------

@app.get("/api/remote/profiles", response_model=RemoteProfilesResponse)
async def get_remote_profiles() -> RemoteProfilesResponse:
    """저장된 원격 서버 프로파일 목록을 반환한다(비밀 미포함)."""
    raw = remote_module.list_remote_profiles()
    profiles = [
        RemoteProfile(
            name=p["name"],
            host=p["host"],
            port=p["port"],
            username=p["username"],
            auth_type=p["authType"],  # type: ignore[arg-type]
            key_path=p.get("keyPath"),
            default_path=p.get("defaultPath"),
        )
        for p in raw
    ]
    return RemoteProfilesResponse(profiles=profiles)


@app.get("/api/remote/profiles/health", response_model=ProfileHealthResponse)
def remote_profiles_health() -> ProfileHealthResponse:
    """저장된 프로파일들의 도달성을 TCP 연결로 동시 점검한다(인증 미수행)."""
    results = [
        ProfileHealth(name=r["name"], reachable=r["reachable"], latency_ms=r["latencyMs"])
        for r in remote_module.check_all_reachable()
    ]
    return ProfileHealthResponse(results=results)


@app.post("/api/remote/profiles", response_model=OkResponse)
async def save_remote_profile(body: SaveRemoteProfileRequest) -> OkResponse:
    """원격 프로파일을 저장한다(비밀은 Keychain)."""
    remote_module.save_remote_profile(
        name=body.name,
        host=body.host,
        port=body.port,
        username=body.username,
        auth_type=body.auth_type,
        key_path=body.key_path,
        secret=body.secret,
    )
    return OkResponse(ok=True)


@app.delete("/api/remote/profiles/{name}", response_model=OkResponse)
async def delete_remote_profile(name: str) -> OkResponse:
    """원격 프로파일을 삭제한다."""
    remote_module.delete_remote_profile(name)
    return OkResponse(ok=True)


@app.post("/api/remote/connect")
def remote_connect(body: dict) -> JSONResponse:
    """원격 서버에 SSH 연결을 맺고 활성 세션에 저장한다.

    body:
      - { mode: "profile", profileName }
      - { mode: "adhoc", host, port?, username, authType, keyPath?, secret? }
    """
    return _connect_into(_remote, body)


@app.get("/api/remote/connection", response_model=RemoteConnectionStatusResponse)
async def get_remote_connection() -> RemoteConnectionStatusResponse:
    """현재 원격 연결 상태를 반환한다."""
    if not _remote.connected:
        return RemoteConnectionStatusResponse(connected=False)
    return RemoteConnectionStatusResponse(
        connected=True,
        host=_remote.host,
        username=_remote.username,
        home_dir=_remote.home_dir,
        default_path=_remote.default_path,
        profile_name=_remote.profile_name,
    )


@app.post("/api/remote/profiles/{name}/default-path", response_model=OkResponse)
async def set_remote_default_path(name: str, body: SetDefaultPathRequest) -> OkResponse:
    """프로파일의 기본 탐색 폴더를 저장한다."""
    ok = remote_module.set_default_path(name, body.path)
    if not ok:
        raise HTTPException(status_code=404, detail=f"원격 프로파일을 찾을 수 없습니다: {name}")
    # 현재 연결된 프로파일이면 메모리 세션도 갱신
    if _remote.profile_name == name:
        _remote.default_path = body.path or None
    return OkResponse(ok=True)


@app.get("/api/remote/flat", response_model=FlatSummaryResponse)
def remote_flat(path: str = "") -> FlatSummaryResponse:
    """원격 path 하위 전체 파일 수·총 바이트(추천/여유공간 비교용)."""
    ssh = _remote.require_ssh()
    try:
        s = sftp_engine.flat_summary(ssh, path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"요약 조회 실패: {exc}")
    return FlatSummaryResponse(total_files=s["totalFiles"], total_bytes=s["totalBytes"])


@app.get("/api/remote/diskspace", response_model=DiskSpaceResponse)
def remote_diskspace(path: str = "") -> DiskSpaceResponse:
    """원격 path가 속한 파일시스템의 여유 공간(byte)."""
    ssh = _remote.require_ssh()
    try:
        info = sftp_engine.disk_space(ssh, path or (_remote.home_dir or "."))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"여유 공간 조회 실패: {exc}")
    return DiskSpaceResponse(total=info["total"], free=info["free"], used=info["used"])


@app.post("/api/remote/measure", response_model=MeasureResponse)
def remote_measure(body: SetDefaultPathRequest) -> MeasureResponse:
    """Mac↔원격 전송 속도를 임시 프로브로 측정한다(body.path 위치 사용)."""
    ssh = _remote.require_ssh()
    try:
        res = sftp_engine.measure_throughput(ssh, body.path or (_remote.home_dir or "."))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"속도 측정 실패: {exc}")
    return MeasureResponse(
        upload_bps=res["uploadBps"], download_bps=res["downloadBps"], size_bytes=res["sizeBytes"]
    )


@app.post("/api/local/flat", response_model=FlatSummaryResponse)
def local_flat(body: LocalFlatRequest) -> FlatSummaryResponse:
    """로컬 파일/폴더 목록의 전체 파일 수·총 바이트(업로드 추천용)."""
    import os
    total_files = 0
    total_bytes = 0
    for raw in body.paths:
        p = os.path.expanduser(raw)
        try:
            if os.path.isfile(p):
                total_files += 1
                total_bytes += os.path.getsize(p)
            elif os.path.isdir(p):
                for dirpath, _dirs, files in os.walk(p):
                    for fn in files:
                        fp = os.path.join(dirpath, fn)
                        try:
                            total_bytes += os.path.getsize(fp)
                            total_files += 1
                        except OSError:
                            pass
        except OSError:
            pass
    return FlatSummaryResponse(total_files=total_files, total_bytes=total_bytes)


@app.get("/api/local/diskspace", response_model=DiskSpaceResponse)
async def local_diskspace(path: str = "") -> DiskSpaceResponse:
    """로컬 path가 속한 디스크의 여유 공간(byte)."""
    import os
    target = path or str(settings.DEFAULT_DOWNLOAD_DIR)
    # 존재하지 않는 경로면 존재하는 상위로 거슬러 올라가 측정
    probe = target
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        usage = shutil.disk_usage(probe or "/")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"여유 공간 조회 실패: {exc}")
    return DiskSpaceResponse(total=usage.total, free=usage.free, used=usage.used)


@app.post("/api/remote/disconnect", response_model=OkResponse)
async def remote_disconnect() -> OkResponse:
    """원격 연결을 종료한다."""
    _remote.disconnect()
    return OkResponse(ok=True)


@app.get("/api/remote/objects", response_model=ObjectsResponse)
def list_remote_objects(path: str = "") -> ObjectsResponse:
    """원격 디렉터리의 한 레벨을 열거한다. path가 비면 홈 디렉터리."""
    ssh = _remote.require_ssh()
    try:
        result = sftp_engine.list_one_level(ssh, path)
    except Exception as exc:
        # transport가 죽었으면 연결 끊김(409, 재연결 유도), 살아 있으면 경로 문제(400).
        transport = ssh.get_transport()
        if transport is None or not transport.is_active():
            _remote.disconnect()
            raise HTTPException(
                status_code=409, detail="원격 서버 연결이 끊겼습니다. 다시 연결하세요."
            )
        raise HTTPException(status_code=400, detail=f"경로를 열 수 없습니다: {exc}")

    folders = [S3Folder(**f) for f in result["folders"]]
    objects = [
        S3Object(key=o["key"], size=o["size"], last_modified=o["lastModified"])
        for o in result["objects"]
    ]
    # 실제 열거된 디렉터리(정규화 경로)를 prefix로 돌려준다.
    resolved = path or (_remote.home_dir or "")
    return ObjectsResponse(prefix=resolved, folders=folders, objects=objects)


@app.post("/api/remote/folder", response_model=OkResponse)
def create_remote_folder(body: RemoteFolderRequest) -> OkResponse:
    """원격에 디렉터리를 생성한다(상위 경로 포함)."""
    ssh = _remote.require_ssh()
    if not body.path.strip().strip("/"):
        raise HTTPException(status_code=422, detail="폴더 경로가 비어 있습니다.")
    try:
        sftp_engine.make_dir(ssh, body.path)
    except Exception as exc:
        transport = ssh.get_transport()
        if transport is None or not transport.is_active():
            _remote.disconnect()
            raise HTTPException(status_code=409, detail="원격 서버 연결이 끊겼습니다. 다시 연결하세요.")
        raise HTTPException(status_code=400, detail=f"폴더 생성 실패: {exc}")
    return OkResponse(ok=True)


@app.post("/api/remote/download", response_model=JobIdResponse)
async def start_remote_download(body: RemoteDownloadRequest) -> JobIdResponse:
    """원격 → 로컬 다운로드 잡을 생성한다. remoteDirs 또는 keys 중 하나 필수."""
    if not body.remote_dirs and not body.keys:
        raise HTTPException(status_code=422, detail="remoteDirs 또는 keys 중 하나가 필요합니다.")
    ssh = _remote.require_ssh()
    prefs_module.set_last_download_dir(body.local_dir)
    job_id = job_manager.submit_remote_download(
        ssh,
        body.local_dir,
        remote_dirs=body.remote_dirs,
        keys=body.keys,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


@app.post("/api/remote/upload", response_model=JobIdResponse)
async def start_remote_upload(body: RemoteUploadRequest) -> JobIdResponse:
    """로컬 → 원격 업로드 잡을 생성한다."""
    ssh = _remote.require_ssh()
    job_id = job_manager.submit_remote_upload(
        ssh,
        body.remote_dir,
        body.local_paths,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# S3 ↔ 원격 전송 (Mac 경유 없이 직통 우선, 양쪽 세션 모두 필요)
# ---------------------------------------------------------------------------

@app.post("/api/transfer/s3-to-remote", response_model=JobIdResponse)
async def start_s3_to_remote(body: S3ToRemoteRequest) -> JobIdResponse:
    """S3 → 원격 전송 잡을 생성한다. S3·원격 세션 모두 연결 필요."""
    if not body.prefixes and not body.keys:
        raise HTTPException(status_code=422, detail="prefixes 또는 keys 중 하나가 필요합니다.")
    client = _session.require_client()
    ssh = _remote.require_ssh()
    job_id = job_manager.submit_s3_to_remote(
        client, ssh, body.bucket,
        prefixes=body.prefixes, keys=body.keys, remote_dir=body.remote_dir,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


@app.post("/api/transfer/remote-to-s3", response_model=JobIdResponse)
async def start_remote_to_s3(body: RemoteToS3Request) -> JobIdResponse:
    """원격 → S3 전송 잡을 생성한다. S3·원격 세션 모두 연결 필요."""
    if not body.remote_dirs and not body.keys:
        raise HTTPException(status_code=422, detail="remoteDirs 또는 keys 중 하나가 필요합니다.")
    client = _session.require_client()
    ssh = _remote.require_ssh()
    job_id = job_manager.submit_remote_to_s3(
        ssh, client, body.bucket,
        remote_dirs=body.remote_dirs, keys=body.keys, prefix=body.prefix,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


@app.post("/api/transfer/remote-to-remote", response_model=JobIdResponse)
async def start_remote_to_remote(body: RemoteToRemoteRequest) -> JobIdResponse:
    """원격(소스) → 원격B(대상) 전송. 두 원격 세션 모두 연결 필요(Mac 경유 릴레이)."""
    if not body.src_dirs and not body.src_keys:
        raise HTTPException(status_code=422, detail="srcDirs 또는 srcKeys 중 하나가 필요합니다.")
    ssh_src = _remote.require_ssh()
    ssh_dst = _remote_b.require_ssh()
    job_id = job_manager.submit_remote_to_remote(
        ssh_src, ssh_dst,
        src_dirs=body.src_dirs, src_keys=body.src_keys, dest_dir=body.dest_dir,
        max_workers=body.max_workers,
    )
    return JobIdResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# 두 번째 원격(remote-b) — 원격↔원격 전송의 대상 서버
# ---------------------------------------------------------------------------

@app.post("/api/remote-b/connect")
def remote_b_connect(body: dict) -> JSONResponse:
    """대상 원격(B) 서버에 연결한다(프로파일/adhoc)."""
    return _connect_into(_remote_b, body)


@app.get("/api/remote-b/connection", response_model=RemoteConnectionStatusResponse)
async def get_remote_b_connection() -> RemoteConnectionStatusResponse:
    if not _remote_b.connected:
        return RemoteConnectionStatusResponse(connected=False)
    return RemoteConnectionStatusResponse(
        connected=True, host=_remote_b.host, username=_remote_b.username,
        home_dir=_remote_b.home_dir, default_path=_remote_b.default_path,
        profile_name=_remote_b.profile_name,
    )


@app.post("/api/remote-b/disconnect", response_model=OkResponse)
async def remote_b_disconnect() -> OkResponse:
    _remote_b.disconnect()
    return OkResponse(ok=True)


@app.get("/api/remote-b/objects", response_model=ObjectsResponse)
def list_remote_b_objects(path: str = "") -> ObjectsResponse:
    ssh = _remote_b.require_ssh()
    try:
        result = sftp_engine.list_one_level(ssh, path)
    except Exception as exc:
        transport = ssh.get_transport()
        if transport is None or not transport.is_active():
            _remote_b.disconnect()
            raise HTTPException(status_code=409, detail="대상 원격 연결이 끊겼습니다. 다시 연결하세요.")
        raise HTTPException(status_code=400, detail=f"경로를 열 수 없습니다: {exc}")
    folders = [S3Folder(**f) for f in result["folders"]]
    objects = [
        S3Object(key=o["key"], size=o["size"], last_modified=o["lastModified"])
        for o in result["objects"]
    ]
    resolved = path or (_remote_b.home_dir or "")
    return ObjectsResponse(prefix=resolved, folders=folders, objects=objects)


@app.get("/api/remote-b/diskspace", response_model=DiskSpaceResponse)
def remote_b_diskspace(path: str = "") -> DiskSpaceResponse:
    ssh = _remote_b.require_ssh()
    try:
        info = sftp_engine.disk_space(ssh, path or (_remote_b.home_dir or "."))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"여유 공간 조회 실패: {exc}")
    return DiskSpaceResponse(total=info["total"], free=info["free"], used=info["used"])


# ---------------------------------------------------------------------------
# 로컬 / 시스템 (Native bridge)
# ---------------------------------------------------------------------------

@app.post("/api/pick-folder", response_model=PickFolderResponse)
async def pick_folder() -> PickFolderResponse:
    """네이티브 폴더 선택 다이얼로그를 열고 선택된 경로를 반환한다."""
    if _native_bridge is None:
        # 개발 모드: 빈 결과 반환
        return PickFolderResponse(path=None)
    try:
        path = _native_bridge.pick_folder()
        return PickFolderResponse(path=path)
    except Exception as exc:
        logger.warning("pick_folder 실패: %s", exc)
        return PickFolderResponse(path=None)


@app.post("/api/pick-files", response_model=PickFilesResponse)
async def pick_files() -> PickFilesResponse:
    """네이티브 파일 선택 다이얼로그를 열고 선택된 경로 목록을 반환한다."""
    if _native_bridge is None:
        return PickFilesResponse(paths=[])
    try:
        paths = _native_bridge.pick_files()
        return PickFilesResponse(paths=paths or [])
    except Exception as exc:
        logger.warning("pick_files 실패: %s", exc)
        return PickFilesResponse(paths=[])


@app.post("/api/reveal", response_model=OkResponse)
async def reveal(body: RevealRequest) -> OkResponse:
    """Finder에서 경로를 연다."""
    if _native_bridge is None:
        raise HTTPException(status_code=501, detail="네이티브 브릿지가 주입되지 않았습니다.")
    try:
        _native_bridge.reveal(body.path)
        return OkResponse(ok=True)
    except Exception as exc:
        logger.warning("reveal 실패: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# WebSocket — 진행률 스트림
# ---------------------------------------------------------------------------

@app.websocket("/api/ws/jobs/{job_id}")
async def ws_job_progress(websocket: WebSocket, job_id: str) -> None:
    """잡 진행률을 실시간으로 push한다.

    연결 즉시 현재 잡 스냅샷을 1회 전송한 뒤 이벤트를 push한다.
    """
    # 토큰 검증 (HTTP 미들웨어는 WebSocket을 가로채지 않으므로 여기서 직접 확인)
    token = websocket.query_params.get("token") or websocket.headers.get("x-s3m-token")
    if not _is_token_valid(token):
        await websocket.close(code=4401)  # 정책 위반(인증 실패)
        return

    await websocket.accept()

    job = job_manager.get_job(job_id)
    if not job:
        await websocket.send_json({"type": "error", "message": f"잡을 찾을 수 없습니다: {job_id}"})
        await websocket.close()
        return

    # 스냅샷 1회 전송
    await websocket.send_json(job.to_dict())

    # 이미 완료된 잡이면 바로 닫기
    if job.status in ("done", "error", "canceled"):
        await websocket.close()
        return

    queue = job_manager.subscribe(job_id)
    if queue is None:
        await websocket.close()
        return

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # 타임아웃 시 ping 대신 재확인
                if job.status in ("done", "error", "canceled"):
                    break
                continue

            await websocket.send_json(event)

            # 종료 이벤트면 루프 탈출
            if event.get("type") in ("done", "error", "canceled"):
                break

    except WebSocketDisconnect:
        logger.debug("WebSocket 연결 종료 (job_id=%s)", job_id)
    except Exception as exc:
        logger.warning("WebSocket 오류 (job_id=%s): %s", job_id, exc)
    finally:
        job_manager.unsubscribe(job_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 정적 서빙 (§4)
# ---------------------------------------------------------------------------

_dist_dir = settings.frontend_dist_dir()
_index_html = _dist_dir / "index.html"

_DEV_MESSAGE = (
    "<html><body style='font-family:sans-serif;padding:2rem;'>"
    "<h2>Data Manager — 개발 모드</h2>"
    "<p>프론트엔드 빌드가 없습니다. <code>frontend/dist</code> 디렉터리를 생성해주세요.</p>"
    "<p>API 서버는 정상 동작 중입니다: "
    "<a href='/api/health'>/api/health</a></p>"
    "</body></html>"
)

if _dist_dir.exists() and _index_html.exists():
    # 빌드된 에셋(js/css/favicon 등)은 StaticFiles로 서빙하되,
    # 존재하지 않는 경로는 아래 catch-all이 index.html로 폴백한다(SPA, §4).
    app.mount("/assets", StaticFiles(directory=str(_dist_dir / "assets")), name="assets")
    logger.info("프론트엔드 정적 파일 서빙: %s", _dist_dir)


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str) -> Any:
    """비-/api 경로 처리: 실제 파일이면 그 파일을, 아니면 index.html로 폴백(§4).

    /api/* 와 WebSocket 라우트는 이 catch-all보다 먼저 등록되어 우선 매칭된다.
    """
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="없는 API 경로입니다.")

    if not (_dist_dir.exists() and _index_html.exists()):
        # 빌드 없음 — 개발 안내 페이지
        return HTMLResponse(content=_DEV_MESSAGE)

    # dist 내부의 실제 파일이면 그대로 반환(favicon.svg 등 루트 파일 대응).
    if full_path:
        candidate = (_dist_dir / full_path).resolve()
        try:
            candidate.relative_to(_dist_dir.resolve())  # 경로 탈출 방지
            if candidate.is_file():
                return FileResponse(str(candidate))
        except ValueError:
            pass

    # 그 외 모든 경로는 SPA 진입점으로 폴백
    return FileResponse(str(_index_html))
