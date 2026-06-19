# 🚀 Data Manager

메뉴바 기반 **AWS S3 + 원격 SFTP 서버** 다운로드 · 업로드 macOS 데스크톱 앱.

> 기존 Gradio 기반 `s3_downloader_portable`을 React UI + 네이티브 앱으로 재설계한 버전입니다.

- 🧭 **메뉴바 상주** — 상단 메뉴바 아이콘 클릭으로 네이티브 창이 열립니다 (Dock 미표시).
- ⚛️ **React + Tailwind UI** — 다크 테마, 버킷/폴더 트리 탐색기, 실시간 진행률.
- 🔀 **S3 / 원격 모드 전환** — 상단 토글로 S3와 SFTP 원격 서버를 오가며 사용.
- 🔐 **자격증명 안전 저장** — macOS Keychain + `~/.aws` 프로파일, SSH 키 + Keychain 모두 지원.
- ⬇️⬆️ **다운로드 / 업로드** — 로컬↔S3, 로컬↔원격 서버. 동시 전송, 취소/이력 지원.
- 📦 **단일 `.app` 배포** — PyInstaller로 독립 실행 앱 빌드.

## 아키텍처

```
[메뉴바 트레이 (pystray)] ──클릭──> [네이티브 창 (pywebview)]
                                          │ loads
                                          ▼
                            http://127.0.0.1:8765  (FastAPI, 로컬 전용)
                            ├─ /          → React 빌드(frontend/dist)
                            ├─ /api/*      → REST (자격증명/탐색/전송)
                            └─ /api/ws/... → WebSocket (실시간 진행률)
```

- **Backend** (`src/s3manager/core`, `server`): boto3 S3 엔진 + paramiko SFTP 엔진 + FastAPI. S3/원격 활성 세션을 각각 메모리에 보관.
- **Frontend** (`frontend/`): Vite + React + TypeScript + Tailwind.
- **Shell** (`src/s3manager/shell`): pystray 메뉴바 + pywebview 창 + 네이티브 파일 다이얼로그.
- 자세한 인터페이스는 [`API_CONTRACT.md`](API_CONTRACT.md) 참고.

## 개발 실행

```bash
# 1) Python 의존성 (3.11~3.12 권장)
uv venv --python 3.12
uv pip install -e .

# 2) 프론트엔드 빌드
cd frontend && npm install && npm run build && cd ..

# 3) 앱 실행 (메뉴바 + 창)
uv run data-manager
#   또는: uv run python -m s3manager.shell.main
```

### 프론트엔드 핫리로드 개발

```bash
# 터미널 A — 백엔드만
uv run python -m uvicorn s3manager.server.app:app --port 8765 --reload
# 터미널 B — Vite dev 서버 (/api 프록시 → 8765)
cd frontend && npm run dev
```

## `.app` 빌드 & 배포

```bash
bash packaging/build.sh
# 산출물:
#   dist/Data Manager.app          (실행용)
#   dist/S3-Manager-arm64.zip    ← 동료에게 전달하는 배포본
```

빌드 순서: `frontend/dist` → PyInstaller(`packaging/s3manager.spec`) → ad-hoc 코드서명 → 배포용 zip(ditto).

### 다른 사람에게 배포
1. `bash packaging/build.sh` 로 zip 생성.
2. `dist/S3-Manager-<arch>.zip` 을 동료에게 전달.
3. 받는 사람은 [`INSTALL.md`](INSTALL.md) 따라 설치(압축 해제 → /Applications → 첫 실행 우클릭 "열기").

> ad-hoc 서명만 하므로 받는 쪽에서 첫 실행 시 Gatekeeper 경고가 뜬다(우클릭 열기 또는 `xattr -dr com.apple.quarantine`로 해결 — INSTALL.md 참고). 경고를 완전히 없애려면 Apple Developer ID 서명 + 공증(notarize)이 필요하다(유료 계정).

### 아키텍처 (arm64 / universal2)
기본은 **arm64(Apple Silicon 전용)**. Intel까지 지원하는 **universal2**는 인터프리터가 universal2여야 빌드된다 — uv/brew의 Python은 arm64 전용이라 불가. universal2 빌드 절차:

```bash
# 1) python.org universal2 Python 3.12 설치 (관리자 권한)
#    https://www.python.org/downloads/macos/  (macOS 64-bit universal2 installer)
# 2) 그 Python으로 venv 재생성 + 의존성 설치 (대부분 universal2 휠 제공)
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m venv .venv
.venv/bin/pip install -e . pyinstaller
# 3) universal2로 빌드
S3M_ARCH=universal2 bash packaging/build.sh   # → dist/S3-Manager-universal2.zip
```

> ⚠️ 프로젝트 이동/venv 재생성 후에는 반드시 `.venv`를 다시 만들 것. 콘솔스크립트(예: pyinstaller) shebang이 옛 경로를 가리켜 깨진다.

## 주요 기능

| 화면 | 설명 |
|---|---|
| **모드 토글** | 상단 바에서 **S3 / 원격(SFTP)** 전환. 각 모드의 연결은 독립적으로 유지. |
| **연결 (S3)** | AWS 프로파일 선택 / 직접 키 입력 / 새 프로파일 Keychain 저장. 연결 시 계정·ARN 확인. |
| **연결 (원격)** | SFTP 호스트·포트·사용자 입력. SSH 키(passphrase) 또는 비밀번호 인증. 프로파일로 저장 가능(비밀은 Keychain). |
| **트리 탐색기** | S3: 버킷→폴더 lazy-load / 원격: 홈 디렉터리부터 폴더 lazy-load. 체크박스로 전송 대상 선택. |
| **다운로드** | 저장 경로 선택, 동시 전송 수 조절, 실시간 진행률(속도/ETA), 취소. |
| **업로드** | 파일/폴더(재귀) 선택 → S3 버킷/prefix 또는 원격 디렉터리(자동 생성)로 업로드. |
| **작업 이력** | 최근 작업 상태 확인(S3·원격 공통), 완료 후 Finder에서 열기. |

> 원격 모드 트리는 연결한 계정의 **홈 디렉터리**를 루트로 표시합니다. 그 밖의 절대 경로로 업로드하려면 업로드 화면의 "대상 원격 경로"에 직접 입력하면 됩니다.

## 자격증명은 어디에 넣나요?

세 가지 방법 중 편한 것을 쓰면 됩니다 (모두 앱 **연결** 화면에서 선택).

1. **직접 입력** — Access Key / Secret Key를 그때그때 입력. 메모리에만 보관(저장 안 함).
2. **Keychain 저장** — 연결 화면의 "새 프로파일 저장"으로 macOS Keychain에 안전 보관. 다음부터 프로파일만 고르면 됨.
3. **`~/.aws/credentials` 프로파일** — AWS CLI 표준 위치. 이미 있으면 자동 감지되어 목록에 뜸:
   ```ini
   # ~/.aws/credentials
   [default]
   aws_access_key_id = AKIA...
   aws_secret_access_key = ...
   [my-prod]
   aws_access_key_id = AKIA...
   aws_secret_access_key = ...
   ```

## 자동 실행 (로그인 시 항상 메뉴바 상주)

```bash
# 1) 앱을 /Applications 로 이동 (권장)
mv "dist/Data Manager.app" /Applications/

# 2) 자동 실행 등록 (LaunchAgent)
bash packaging/install_autostart.sh

# 해제
bash packaging/uninstall_autostart.sh
```

- 로그인하면 자동으로 메뉴바에 상주합니다(RunAtLoad).
- 크래시 시 자동 재시작, 트레이 **"종료"** 로 끈 경우엔 다음 로그인까지 재시작하지 않습니다.
- (대안) **시스템 설정 → 일반 → 로그인 항목**에 `.app`을 추가해도 됩니다.

## 보안

- 🛡️ **S3 객체 삭제 기능 없음 (설계상 보장)**: 이 도구는 S3에 대해 읽기(list/get)와 업로드(put)만
  수행합니다. 코드 어디에도 `delete_object` 등 삭제 API를 호출하는 경로가 없으며, 동기화도
  변경분 복사만 합니다 (S3·로컬 무엇도 삭제하지 않음).
- FastAPI는 `127.0.0.1:8765`에만 바인딩 — 다른 기기에서 접근 불가.
- **로컬 접근 토큰**: 실행마다 무작위 토큰을 발급하고, 앱 창에만 전달합니다.
  토큰을 모르는 같은 Mac의 **다른 사용자·프로세스·브라우저는 `/api/*` 호출 시 401**로 차단됩니다.
- **Host 헤더 검증**으로 악성 웹사이트의 DNS 리바인딩 공격을 차단합니다.
- 자격증명 평문은 디스크에 쓰지 않음. Keychain 저장은 `keyring` 경유. 원격 서버의 비밀(SSH 키 passphrase·비밀번호)도 Keychain에만 저장(메타데이터만 `remote_profiles.json`).
- Keychain 프로파일 이름 인덱스만 `~/Library/Application Support/S3Manager/`에 보관.
- ⚠️ 원격 SFTP 연결은 편의를 위해 호스트 키를 자동 수락(AutoAddPolicy)합니다 — 신뢰할 수 있는 서버에만 연결하세요.

> ⚠️ 토큰은 네트워크/타 프로세스 접근을 막아줍니다. 다만 앱이 연결된 상태로 떠 있을 때
> **물리적으로 같은 화면 앞에 앉은 사람**은 창을 조작할 수 있으니, 자리를 비울 땐 화면 잠금을 권장합니다.

## 프로젝트 구조

```
data-manager/
├── API_CONTRACT.md           # 컴포넌트 간 인터페이스 계약
├── pyproject.toml
├── qa_pipeline_test.py       # 잡/WebSocket 파이프라인 스모크 테스트
├── qa_sftp_test.py           # SFTP 엔진 E2E(인메모리 SFTP 서버)
├── qa_remote_http_test.py    # /api/remote/* HTTP E2E
├── assets/                   # 트레이/앱 아이콘 (+ generate_icons.py)
├── packaging/
│   ├── s3manager.spec        # PyInstaller 설정
│   └── build.sh              # 빌드 스크립트
├── frontend/                 # React (Vite + TS + Tailwind)
└── src/s3manager/
    ├── settings.py           # 포트/경로/상수 (단일 소스)
    ├── core/                 # s3_engine · sftp_engine · credentials · remote_profiles · jobs
    ├── server/               # FastAPI app · pydantic models
    └── shell/                # main · tray · bridge
```
