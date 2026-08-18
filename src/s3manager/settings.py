"""앱 전역 설정 — 모든 컴포넌트(backend/shell)가 공유하는 단일 소스.

⚠️ 이 파일은 메인(통합 담당)이 소유합니다. 백엔드/셸 에이전트는 값을 읽기만 하세요.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 플랫폼 분기 — 셸(창·트레이·알림·자동시작)과 사용자 데이터 경로가 갈린다.
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"

APP_NAME = "Data Manager"
APP_ID = "io.github.go-minseong.datamanager"

# 로컬 FastAPI 서버 바인딩 (외부 노출 금지)
HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"

# Keychain(서비스 이름) — keyring이 macOS Keychain에 저장할 때 사용
KEYRING_SERVICE = "io.github.go-minseong.datamanager"

# 앱 사용자 데이터 디렉터리 (이력/설정 저장용)
# macOS 경로는 기존 사용자 데이터 보존을 위해 절대 바꾸지 않는다(폴더명 S3Manager는 역사적 이유).
if IS_WINDOWS:
    _appdata = os.environ.get("APPDATA")
    APP_SUPPORT_DIR = (
        Path(_appdata) / "DataManager"
        if _appdata
        else Path.home() / "AppData" / "Roaming" / "DataManager"
    )
else:
    APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "S3Manager"

# 기본 다운로드 경로
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "s3_downloads"

# 기본 AWS 리전
DEFAULT_REGION = "ap-northeast-2"


def is_frozen() -> bool:
    """PyInstaller 번들로 실행 중인지 여부."""
    return getattr(sys, "frozen", False)


def resource_root() -> Path:
    """정적 리소스(프론트엔드 빌드, 아이콘)의 루트 경로.

    - 개발: 프로젝트 루트
    - 번들(.app): sys._MEIPASS
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # src/s3manager/settings.py -> 프로젝트 루트
    return Path(__file__).resolve().parents[2]


def frontend_dist_dir() -> Path:
    """빌드된 React 정적 파일 디렉터리."""
    return resource_root() / "frontend" / "dist"


def assets_dir() -> Path:
    """트레이 아이콘 등 에셋 디렉터리."""
    return resource_root() / "assets"
