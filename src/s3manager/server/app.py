"""FastAPI 앱.

API 계약서의 모든 REST(§2), WebSocket(§3), 정적 서빙(§4)을 구현한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, Union

import boto3
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from s3manager import __version__, settings
from s3manager.core import credentials as creds_module
from s3manager.core import preferences as prefs_module
from s3manager.core import s3_engine
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
    RevealRequest,
    S3Folder,
    S3Object,
    SaveCredentialsRequest,
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

# ---------------------------------------------------------------------------
# FastAPI 앱 생성
# ---------------------------------------------------------------------------

app = FastAPI(title="S3 Manager API", version=__version__)


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
    logger.info("S3 Manager 백엔드 시작 (포트 %s)", settings.PORT)


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
async def connect(body: dict) -> JSONResponse:
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


# ---------------------------------------------------------------------------
# 탐색
# ---------------------------------------------------------------------------

@app.get("/api/buckets", response_model=BucketsResponse)
async def list_buckets() -> BucketsResponse:
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
async def objects_flat(bucket: str, prefix: str = "") -> FlatSummaryResponse:
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
async def list_objects(bucket: str, prefix: str = "") -> ObjectsResponse:
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


# ---------------------------------------------------------------------------
# 전송 작업
# ---------------------------------------------------------------------------

@app.post("/api/download", response_model=JobIdResponse)
async def start_download(body: DownloadRequest) -> JobIdResponse:
    """다운로드 잡을 생성한다. prefix 또는 keys 중 하나 필수."""
    if body.prefix is None and not body.keys:
        raise HTTPException(status_code=422, detail="prefix 또는 keys 중 하나가 필요합니다.")
    client = _session.require_client()
    # 이 경로를 "마지막 사용 다운로드 경로"로 저장 → 다음 실행 시 기본값으로 사용
    prefs_module.set_last_download_dir(body.local_dir)
    job_id = job_manager.submit_download(
        client,
        body.bucket,
        body.local_dir,
        prefix=body.prefix,
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
    "<h2>S3 Manager — 개발 모드</h2>"
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
