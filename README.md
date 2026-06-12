# 🚀 S3 Manager

메뉴바 기반 **AWS S3 다운로드 · 업로드 · 동기화** macOS 데스크톱 앱.

> 기존 Gradio 기반 `s3_downloader_portable`을 React UI + 네이티브 앱으로 재설계한 버전입니다.

- 🧭 **메뉴바 상주** — 상단 메뉴바 아이콘 클릭으로 네이티브 창이 열립니다 (Dock 미표시).
- ⚛️ **React + Tailwind UI** — 다크 테마, 버킷/폴더 트리 탐색기, 실시간 진행률.
- 🔐 **자격증명 안전 저장** — macOS Keychain + `~/.aws` 프로파일 모두 지원.
- ⬇️⬆️🔄 **다운로드 / 업로드 / 동기화** — 변경분만 동기화, 동시 전송, 취소/이력 지원.
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

- **Backend** (`src/s3manager/core`, `server`): boto3 S3 엔진 + FastAPI. 활성 세션을 메모리에 보관.
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
uv run s3-manager
#   또는: uv run python -m s3manager.shell.main
```

### 프론트엔드 핫리로드 개발

```bash
# 터미널 A — 백엔드만
uv run python -m uvicorn s3manager.server.app:app --port 8765 --reload
# 터미널 B — Vite dev 서버 (/api 프록시 → 8765)
cd frontend && npm run dev
```

## `.app` 빌드 (배포)

```bash
bash packaging/build.sh
# 산출물: dist/S3 Manager.app
```

빌드는 `frontend/dist` → PyInstaller(`packaging/s3manager.spec`) 순서로 진행됩니다.
`.app`은 Apple Silicon(arm64) 전용으로 설정돼 있으며, Intel/Universal은 spec의 `target_arch`를 수정하세요.

## 주요 기능

| 화면 | 설명 |
|---|---|
| **연결** | AWS 프로파일 선택 / 직접 키 입력 / 새 프로파일 Keychain 저장. 연결 시 계정·ARN 확인. |
| **트리 탐색기** | 버킷 → 폴더 lazy-load, 체크박스로 다운로드 대상 선택, 선택 크기 미리보기. |
| **다운로드** | 저장 경로 선택, 동시 다운로드 수 조절, 실시간 진행률(속도/ETA), 취소. |
| **업로드** | 파일/폴더(재귀) 선택 → 버킷/prefix 업로드. |
| **동기화** | down/up 방향, **변경분만 전송**(크기·수정시각 비교). 삭제 없음. |
| **작업 이력** | 최근 작업 상태 확인, 완료 후 Finder에서 열기. |

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
   [nota-prod]
   aws_access_key_id = AKIA...
   aws_secret_access_key = ...
   ```

## 자동 실행 (로그인 시 항상 메뉴바 상주)

```bash
# 1) 앱을 /Applications 로 이동 (권장)
mv "dist/S3 Manager.app" /Applications/

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
- 자격증명 평문은 디스크에 쓰지 않음. Keychain 저장은 `keyring` 경유.
- Keychain 프로파일 이름 인덱스만 `~/Library/Application Support/S3Manager/`에 보관.

> ⚠️ 토큰은 네트워크/타 프로세스 접근을 막아줍니다. 다만 앱이 연결된 상태로 떠 있을 때
> **물리적으로 같은 화면 앞에 앉은 사람**은 창을 조작할 수 있으니, 자리를 비울 땐 화면 잠금을 권장합니다.

## 프로젝트 구조

```
s3-manager/
├── API_CONTRACT.md           # 컴포넌트 간 인터페이스 계약
├── pyproject.toml
├── qa_pipeline_test.py       # 잡/WebSocket 파이프라인 스모크 테스트
├── assets/                   # 트레이/앱 아이콘 (+ generate_icons.py)
├── packaging/
│   ├── s3manager.spec        # PyInstaller 설정
│   └── build.sh              # 빌드 스크립트
├── frontend/                 # React (Vite + TS + Tailwind)
└── src/s3manager/
    ├── settings.py           # 포트/경로/상수 (단일 소스)
    ├── core/                 # s3_engine · credentials · jobs
    ├── server/               # FastAPI app · pydantic models
    └── shell/                # main · tray · bridge
```
