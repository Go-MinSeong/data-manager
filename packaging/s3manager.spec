# -*- mode: python ; coding: utf-8 -*-
# Data Manager — PyInstaller spec (macOS .app 번들)
#
# 빌드: bash packaging/build.sh   (권장)
# 결과: dist/Data Manager.app
#
# 아키텍처: 환경변수 S3M_ARCH 로 제어 (기본 arm64).
#   - arm64      : Apple Silicon 전용 (현재 uv arm64 Python으로 빌드 가능)
#   - universal2 : Intel + Apple Silicon (python.org universal2 Python 필요)

import os
import sys
from pathlib import Path

# 프로젝트 루트 (spec 파일 위치 기준 상위 디렉터리)
PROJECT_ROOT = Path(SPECPATH).parent

# 플랫폼 — macOS 는 .app 번들, Windows 는 폴더형 exe 로 만든다.
IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

# 타깃 아키텍처 (기본 arm64). universal2는 universal2 Python에서만 빌드 가능.
# Windows 는 아키텍처 지정을 쓰지 않는다(호스트 아키텍처로 빌드).
TARGET_ARCH = None if IS_WINDOWS else os.environ.get("S3M_ARCH", "arm64")

# 앱 아이콘 — macOS .icns / Windows .ico
ICON_PATH = str(
    PROJECT_ROOT / "assets" / ("app_icon.ico" if IS_WINDOWS else "app_icon.icns")
)
if not Path(ICON_PATH).exists():
    ICON_PATH = None  # 아이콘이 없어도 빌드는 되게 둔다

# ------------------------------------------------------------------ #
#  Analysis                                                            #
# ------------------------------------------------------------------ #

# 플랫폼별 hidden imports — 동적 로딩이라 PyInstaller 가 놓친다.
if IS_WINDOWS:
    PLATFORM_HIDDEN = [
        "webview.platforms.edgechromium",  # WebView2 (Win11 기본 내장)
        "webview.platforms.winforms",
        "pystray._win32",
        "keyring.backends.Windows",
        "clr",  # pythonnet — winforms 백엔드가 사용
    ]
else:
    PLATFORM_HIDDEN = [
        "webview.platforms.cocoa",
        "pystray._darwin",
        "keyring.backends.macOS",
        "objc",
        "AppKit",
        "Foundation",
        "WebKit",
    ]

a = Analysis(
    # 진입점 스크립트
    [str(PROJECT_ROOT / "src" / "s3manager" / "shell" / "main.py")],

    pathex=[str(PROJECT_ROOT / "src")],

    # 데이터 파일: (소스, 번들 내 상대 경로)
    datas=[
        # React 빌드 산출물
        (str(PROJECT_ROOT / "frontend" / "dist"), "frontend/dist"),
        # 앱 아이콘 등 에셋
        (str(PROJECT_ROOT / "assets"), "assets"),
    ],

    # hidden imports — 동적 로딩으로 PyInstaller 가 놓칠 수 있는 패키지
    hiddenimports=[
        # boto3 / botocore
        "boto3",
        "botocore",
        "botocore.vendored",
        "botocore.retries",
        "botocore.retries.adaptive",
        "botocore.retries.legacy",
        "botocore.retries.standard",
        "s3transfer",
        "s3transfer.upload",
        "s3transfer.download",
        "s3transfer.copy",
        # FastAPI / uvicorn
        "fastapi",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.uvloop",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.main",
        "websockets",
        "websockets.legacy",
        "websockets.legacy.server",
        # pydantic
        "pydantic",
        "pydantic.deprecated",
        "pydantic.deprecated.class_validators",
        # pywebview (백엔드는 아래에서 플랫폼별로 추가)
        "webview",
        "webview.platforms",
        # pystray (백엔드는 아래에서 플랫폼별로 추가)
        "pystray",
        # pillow
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        # keyring (비밀 저장소 — 백엔드는 아래에서 플랫폼별로 추가)
        "keyring",
        "keyring.backends",
        # 기타
        "multipart",
        "python_multipart",
        "anyio",
        "anyio._backends._asyncio",
        "starlette",
        "starlette.routing",
        "starlette.staticfiles",
        "starlette.responses",
    ] + PLATFORM_HIDDEN,

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 불필요한 대형 패키지 제외
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
        "jupyter",
    ],
    noarchive=False,
    optimize=1,
)

# ------------------------------------------------------------------ #
#  PYZ (순수 Python 아카이브)                                          #
# ------------------------------------------------------------------ #

pyz = PYZ(a.pure)

# ------------------------------------------------------------------ #
#  EXE (단일 실행 파일 — .app 내부에 포함됨)                           #
# ------------------------------------------------------------------ #

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # COLLECT 단계에서 수집
    name="s3manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,       # macOS에서 UPX 는 codesign 깨뜨릴 수 있음
    console=False,   # 터미널 창 없음 (GUI 앱)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,   # 환경변수 S3M_ARCH (기본 arm64, universal2 가능) / Windows=None
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
)

# ------------------------------------------------------------------ #
#  COLLECT (바이너리·라이브러리 수집)                                   #
# ------------------------------------------------------------------ #

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Data Manager" if IS_WINDOWS else "s3manager",
)

# ------------------------------------------------------------------ #
#  BUNDLE (macOS .app 번들)                                            #
# ------------------------------------------------------------------ #

# macOS 에서만 .app 번들을 만든다(Windows 는 위 COLLECT 폴더가 결과물).
app = None if IS_WINDOWS else BUNDLE(
    coll,
    name="Data Manager.app",
    icon=ICON_PATH,
    bundle_identifier="io.github.go-minseong.datamanager",

    # Info.plist 보강
    info_plist={
        # 앱 표시 이름
        "CFBundleName": "Data Manager",
        "CFBundleDisplayName": "Data Manager",
        "CFBundleIdentifier": "io.github.go-minseong.datamanager",
        "CFBundleVersion": "2.4.1",
        "CFBundleShortVersionString": "2.4.1",

        # Dock 아이콘 표시 — 메뉴바 + Dock 병행
        "LSUIElement": False,

        # 최소 macOS 버전
        "LSMinimumSystemVersion": "13.0",

        # 파일 접근 권한 설명 (App Store 미제출이라도 권장)
        "NSDocumentsFolderUsageDescription":
            "S3 업로드/다운로드 파일을 읽고 저장합니다.",
        "NSDownloadsFolderUsageDescription":
            "S3에서 다운로드한 파일을 저장합니다.",
        "NSDesktopFolderUsageDescription":
            "S3 업로드 파일을 선택할 수 있습니다.",

        # 네트워크 접근
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
            "NSExceptionDomains": {
                "127.0.0.1": {
                    "NSExceptionAllowsInsecureHTTPLoads": True,
                },
                "localhost": {
                    "NSExceptionAllowsInsecureHTTPLoads": True,
                },
            },
        },

        # Keychain 접근 그룹
        "keychain-access-groups": ["io.github.go-minseong.datamanager"],

        # 고해상도(Retina) 지원
        "NSHighResolutionCapable": True,

        # Python 인터프리터 환경 변수 정리
        "PyRuntimeLocationsKey": [],
    },
)
