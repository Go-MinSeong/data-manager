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

# 타깃 아키텍처 (기본 arm64). universal2는 universal2 Python에서만 빌드 가능.
TARGET_ARCH = os.environ.get("S3M_ARCH", "arm64")

# ------------------------------------------------------------------ #
#  Analysis                                                            #
# ------------------------------------------------------------------ #

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
        # pywebview (macOS Cocoa 백엔드)
        "webview",
        "webview.platforms",
        "webview.platforms.cocoa",
        # pystray (macOS)
        "pystray",
        "pystray._darwin",
        # pillow
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        # keyring (macOS Keychain)
        "keyring",
        "keyring.backends",
        "keyring.backends.macOS",
        # pyobjc 프레임워크
        "objc",
        "AppKit",
        "Foundation",
        "WebKit",
        # 기타
        "multipart",
        "python_multipart",
        "anyio",
        "anyio._backends._asyncio",
        "starlette",
        "starlette.routing",
        "starlette.staticfiles",
        "starlette.responses",
    ],

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
    target_arch=TARGET_ARCH,   # 환경변수 S3M_ARCH (기본 arm64, universal2 가능)
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets" / "app_icon.icns"),
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
    name="s3manager",
)

# ------------------------------------------------------------------ #
#  BUNDLE (macOS .app 번들)                                            #
# ------------------------------------------------------------------ #

app = BUNDLE(
    coll,
    name="Data Manager.app",
    icon=str(PROJECT_ROOT / "assets" / "app_icon.icns"),
    bundle_identifier="ai.nota.s3manager",

    # Info.plist 보강
    info_plist={
        # 앱 표시 이름
        "CFBundleName": "Data Manager",
        "CFBundleDisplayName": "Data Manager",
        "CFBundleIdentifier": "ai.nota.s3manager",
        "CFBundleVersion": "2.0.0",
        "CFBundleShortVersionString": "2.0.0",

        # ★ Dock 아이콘 숨김 — 메뉴바 전용 앱
        "LSUIElement": True,

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
        "keychain-access-groups": ["ai.nota.s3manager"],

        # 고해상도(Retina) 지원
        "NSHighResolutionCapable": True,

        # Python 인터프리터 환경 변수 정리
        "PyRuntimeLocationsKey": [],
    },
)
