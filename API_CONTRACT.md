# S3 Manager — API 계약서 (SHARED CONTRACT)

이 문서는 **Backend / Frontend / Shell** 세 작업이 동시에 진행되기 위한 단일 진실 공급원이다.
세 에이전트 모두 이 계약을 정확히 준수해야 통합 시 충돌이 없다. 임의로 엔드포인트 이름·필드명을 바꾸지 말 것.

## 0. 런타임 토폴로지

```
[macOS 메뉴바 트레이 (pystray)] ──클릭──> [pywebview 네이티브 창]
                                                │  loads
                                                ▼
                                   http://127.0.0.1:8765/  (FastAPI)
                                   ├─ /            → React 빌드(frontend/dist) 정적 서빙
                                   ├─ /api/*        → REST
                                   └─ /api/ws/...   → WebSocket (진행률)
```

- FastAPI는 **127.0.0.1:8765** 에서만 바인딩 (settings.PORT). 외부 노출 금지.
- 단일 사용자 로컬 앱이므로 "활성 세션(active connection)" 1개를 서버 메모리에 보관한다.
- 자격증명 평문은 **절대 디스크에 쓰지 않는다**(Keychain 저장은 keyring 경유만).

## 1. 데이터 모델 (camelCase로 JSON 직렬화)

```ts
// 자격증명 프로파일 (목록 표시용 — 비밀키 미포함)
Profile = {
  name: string            // 표시 이름 ("default", "my-prod", ...)
  source: "aws" | "keychain"  // ~/.aws/credentials 유래 | 앱이 Keychain에 저장
  region: string | null
}

// 오브젝트 1건
S3Object = {
  key: string
  size: number            // bytes
  lastModified: string    // ISO8601
  isFolder: false
}

// 폴더 (CommonPrefix)
S3Folder = {
  key: string             // "folder/subfolder/" (트레일링 슬래시 포함)
  name: string            // 마지막 세그먼트
  isFolder: true
}

Job = {
  jobId: string
  kind: "download" | "upload" | "sync" | "remote-download" | "remote-upload"
  status: "pending" | "running" | "done" | "error" | "canceled"
  totalFiles: number
  completedFiles: number
  failedFiles: number
  totalBytes: number
  transferredBytes: number
  startedAt: string | null
  finishedAt: string | null
  error: string | null
}
```

## 2. REST 엔드포인트 (prefix: `/api`)

### 자격증명 / 연결
- `GET  /api/profiles` → `{ profiles: Profile[] }`
  - `~/.aws/credentials`·`~/.aws/config`의 프로파일 + Keychain에 저장된 앱 프로파일을 합쳐 반환.
- `POST /api/credentials` (Keychain 저장) body `{ name, accessKeyId, secretAccessKey, region }` → `{ ok: true }`
- `DELETE /api/credentials/{name}` → `{ ok: true }`  (Keychain에서 제거)
- `POST /api/connect` body 중 하나:
  - 직접 키: `{ mode: "keys", accessKeyId, secretAccessKey, region }`
  - 프로파일: `{ mode: "profile", profileName, region? }`  (source가 aws든 keychain이든 동일)
  → 성공 `{ ok: true, identity: { account, arn }, region }` / 실패 `{ ok: false, error: string }`
  - 성공 시 서버 메모리에 "활성 세션" 저장. 이후 buckets/objects/download/upload/sync는 이 세션 사용.
- `GET  /api/connection` → 현재 활성 연결 상태 `{ connected: bool, identity?, region? }`

### 탐색
- `GET  /api/buckets` → `{ buckets: { name: string, region: string|null }[] }`
- `GET  /api/objects?bucket=<b>&prefix=<p>` → 한 레벨만(delimiter="/")
  → `{ prefix: string, folders: S3Folder[], objects: S3Object[] }`
  - prefix 미지정 시 루트. 트리 lazy-load 용도.
- `GET  /api/objects/flat?bucket=<b>&prefix=<p>` → prefix 하위 **전체 파일**(재귀) + 합계
  → `{ totalFiles: number, totalBytes: number }`  (다운로드 전 크기 미리보기용)

### 전송 작업 (비동기 잡)
- `POST /api/download` body `{ bucket, prefix?, keys?: string[], localDir, maxWorkers? }` → `{ jobId }`
  - `prefix` 주면 prefix 하위 전체, `keys` 주면 지정 키만. 둘 중 하나 필수.
- `POST /api/upload` body `{ bucket, prefix, localPaths: string[], maxWorkers? }` → `{ jobId }`
  - `localPaths`는 파일 또는 폴더 경로 혼합 가능. 폴더는 재귀 업로드.
- `POST /api/sync` body `{ direction: "down"|"up", bucket, prefix, localDir, deleteExtra?: bool, maxWorkers? }` → `{ jobId }`
  - 변경분만 전송(크기 + (down)mtime/(up)ETag 비교). `deleteExtra=true`면 대상에만 있는 파일 삭제.
- `GET  /api/jobs` → `{ jobs: Job[] }`  (최근 작업 이력, 최신순)
- `GET  /api/jobs/{jobId}` → `Job`
- `POST /api/jobs/{jobId}/cancel` → `{ ok: true }`

### 원격(SFTP) 서버
S3와 독립된 "활성 원격 연결" 1개를 서버 메모리에 보관한다(SSH/paramiko). 잡·WebSocket·pick/reveal은 S3와 공유한다.
- `GET  /api/remote/profiles` → `{ profiles: RemoteProfile[] }`
  - `RemoteProfile = { name, host, port, username, authType: "key"|"password", keyPath: string|null }` (비밀 미포함)
  - 메타데이터는 `~/Library/Application Support/S3Manager/remote_profiles.json`, 비밀(키 passphrase/password)은 Keychain(`io.github.go-minseong.datamanager.remote`).
- `POST /api/remote/profiles` body `{ name, host, port?, username, authType, keyPath?, secret? }` → `{ ok: true }`
  - `secret`은 Keychain에만 저장. `secret` 생략 시 기존 비밀 유지(메타만 갱신).
- `DELETE /api/remote/profiles/{name}` → `{ ok: true }`
- `POST /api/remote/connect` body 중 하나:
  - 프로파일: `{ mode: "profile", profileName }`
  - 즉석: `{ mode: "adhoc", host, port?, username, authType, keyPath?, secret? }`
  → 성공 `{ ok: true, host, username, homeDir }` / 실패 `{ ok: false, error: string }`
  - `authType="key"`면 secret은 키 passphrase, `"password"`면 로그인 비밀번호로 사용. 키 미지정 시 `~/.ssh` 기본 키·ssh-agent도 시도.
- `GET  /api/remote/connection` → `{ connected: bool, host?, username?, homeDir? }`
- `POST /api/remote/disconnect` → `{ ok: true }`
- `GET  /api/remote/objects?path=<p>` → 한 레벨만 `{ prefix, folders: S3Folder[], objects: S3Object[] }`
  - `path` 미지정 시 홈 디렉터리. S3 `/api/objects`와 응답 형태 동일(프론트 트리 재사용). 폴더 `key`는 트레일링 슬래시 포함, 객체 `key`는 절대 경로.
- `POST /api/remote/download` body `{ remoteDir?, keys?: string[], localDir, maxWorkers? }` → `{ jobId }`
  - `remoteDir` 주면 하위 전체(재귀, 구조 보존), `keys` 주면 지정 파일만(평면). 둘 중 하나 필수. 잡 `kind="remote-download"`.
- `POST /api/remote/upload` body `{ remoteDir, localPaths: string[], maxWorkers? }` → `{ jobId }`
  - `localPaths`는 파일/폴더 혼합. 폴더는 재귀 업로드, 원격 디렉터리 자동 생성. 잡 `kind="remote-upload"`.

### 로컬 / 시스템 (shell 연동)
- `POST /api/pick-folder` → `{ path: string | null }`  네이티브 폴더 선택 다이얼로그.
- `POST /api/pick-files`  → `{ paths: string[] }`       네이티브 파일(복수) 선택.
- `POST /api/reveal` body `{ path }` → `{ ok }`  Finder에서 경로 열기.
- `GET  /api/health` → `{ ok: true, version: string }`

### 환경설정 (UI 영속 설정)
- `GET  /api/preferences` → `{ hiddenBuckets: string[] }`
- `PUT  /api/preferences/hidden-buckets` body `{ hiddenBuckets: string[] }` → `{ hiddenBuckets: string[] }` (정규화: 중복제거+정렬)
  - 저장 위치: `~/Library/Application Support/S3Manager/preferences.json` (민감정보 미저장).

> **pick-folder/pick-files/reveal 구현 협약**: 이 동작은 pywebview(셸)만 할 수 있다.
> 셸은 앱 시작 시 `s3manager.server.app.set_native_bridge(bridge)`를 호출해 콜백을 주입한다.
> bridge 인터페이스:
> ```python
> class NativeBridge(Protocol):
>     def pick_folder(self) -> str | None: ...
>     def pick_files(self) -> list[str]: ...
>     def reveal(self, path: str) -> None: ...
> ```
> 백엔드는 bridge가 주입 안 됐으면(순수 브라우저 개발 모드) 501 또는 빈 결과를 반환한다.

## 3. WebSocket — 진행률 스트림

- 엔드포인트: `WS /api/ws/jobs/{jobId}`
- 연결 즉시 현재 잡 스냅샷(`Job`)을 1회 보낸 뒤, 아래 이벤트를 push.
- 모든 메시지는 JSON. 공통 필드 `type`.

```ts
{ type:"start",    job: Job }
{ type:"progress", completedFiles, totalFiles, transferredBytes, totalBytes,
                   currentFile: string, speedBps: number, etaSec: number|null }
{ type:"file",     key: string, status:"done"|"failed", error?: string }
{ type:"done",     success: number, failure: number, elapsedSec: number }
{ type:"error",    message: string }
{ type:"canceled" }
```

- progress 이벤트는 최소 0.2s 간격으로 throttle(과도한 푸시 방지).

## 4. 정적 서빙 규칙
- FastAPI는 `settings.frontend_dist_dir()`(= `frontend/dist`)를 `/`에 mount.
- SPA 폴백: 알 수 없는 비-`/api` 경로는 `index.html` 반환.
- 빌드 산출물이 없으면(개발 중) `/`는 "프론트엔드 빌드 필요" 안내 텍스트.

## 5. 포트/설정 공유
- 포트·서비스명·경로는 전부 `s3manager.settings`에서 import. **하드코딩 금지.**

## 6. 디렉터리 소유권 (충돌 방지)
- **Backend 에이전트**: `src/s3manager/core/**`, `src/s3manager/server/**` (단, `__init__.py`·`settings.py` 수정 금지)
- **Frontend 에이전트**: `frontend/**` 전부 (scaffold 포함)
- **Shell 에이전트**: `src/s3manager/shell/**`, `packaging/**`, `assets/**`
- 공통 파일(`settings.py`, `pyproject.toml`, `API_CONTRACT.md`)은 메인 전용. 건드리지 말 것.
