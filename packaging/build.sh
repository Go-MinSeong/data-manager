#!/usr/bin/env bash
# S3 Manager 빌드 스크립트
#
# 사용법:
#   cd /path/to/s3-manager
#   bash packaging/build.sh
#
# 빌드 순서:
#   1. 프론트엔드(React) 빌드 → frontend/dist/
#   2. 아이콘 생성 (assets/app_icon.icns 없으면)
#   3. PyInstaller → dist/S3 Manager.app
#
# 요구사항:
#   - Node.js + npm (프론트엔드 빌드)
#   - uv (Python 패키지 관리)
#   - Python 3.12 (venv에 pyinstaller, pywebview, pystray 포함)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== S3 Manager 빌드 시작 ==="
echo "프로젝트 루트: ${PROJECT_ROOT}"
cd "${PROJECT_ROOT}"

# ------------------------------------------------------------------ #
#  1. 프론트엔드 빌드                                                   #
# ------------------------------------------------------------------ #
echo ""
echo "--- [1/3] 프론트엔드 빌드 ---"

if [ ! -d "frontend" ]; then
    echo "오류: frontend/ 디렉터리가 없습니다. Frontend 에이전트가 먼저 실행되어야 합니다."
    exit 1
fi

cd "${PROJECT_ROOT}/frontend"
if [ ! -f "package.json" ]; then
    echo "오류: frontend/package.json 이 없습니다."
    exit 1
fi

# 의존성 설치 (이미 설치된 경우 빠름)
npm install --prefer-offline

# 프로덕션 빌드
npm run build

if [ ! -d "${PROJECT_ROOT}/frontend/dist" ]; then
    echo "오류: 프론트엔드 빌드 실패 (frontend/dist 없음)"
    exit 1
fi
echo "프론트엔드 빌드 완료: frontend/dist/"

cd "${PROJECT_ROOT}"

# ------------------------------------------------------------------ #
#  2. 아이콘 생성                                                       #
# ------------------------------------------------------------------ #
echo ""
echo "--- [2/3] 아이콘 생성 ---"

# PNG/ICNS 아이콘이 없으면 생성
if [ ! -f "assets/app_icon.icns" ] || [ ! -f "assets/tray.png" ]; then
    echo "아이콘 생성 중..."
    uv run python assets/generate_icons.py
else
    echo "아이콘 이미 존재 — 건너뜀 (재생성하려면 assets/ 에서 삭제)"
fi

# iconutil 로 고품질 .icns 재생성 (macOS 전용, 선택사항)
if command -v iconutil &> /dev/null && [ ! -f "assets/app_icon_hires.icns" ]; then
    ICONSET_DIR="assets/app_icon.iconset"
    if [ ! -d "${ICONSET_DIR}" ]; then
        mkdir -p "${ICONSET_DIR}"
        # macOS iconset 표준 크기 복사
        for size in 16 32 64 128 256 512; do
            src="assets/tray_${size}.png"
            if [ -f "${src}" ]; then
                cp "${src}" "${ICONSET_DIR}/icon_${size}x${size}.png"
                # @2x (Retina) — 같은 이미지로 대체
                cp "${src}" "${ICONSET_DIR}/icon_$((size/2))x$((size/2))@2x.png" 2>/dev/null || true
            fi
        done
        # 512@2x
        [ -f "assets/tray_512.png" ] && cp "assets/tray_512.png" "${ICONSET_DIR}/icon_512x512@2x.png" || true
    fi
    iconutil -c icns "${ICONSET_DIR}" -o "assets/app_icon.icns" && \
        echo "iconutil 로 .icns 재생성 완료" || \
        echo "경고: iconutil 실패, PIL 생성 .icns 사용"
fi

# ------------------------------------------------------------------ #
#  3. PyInstaller 빌드                                                  #
# ------------------------------------------------------------------ #
echo ""
echo "--- [3/3] PyInstaller 빌드 ---"

# 이전 빌드 정리 (선택)
if [ -d "dist/S3 Manager.app" ]; then
    echo "기존 dist/S3 Manager.app 삭제 중..."
    rm -rf "dist/S3 Manager.app"
fi

uv run pyinstaller packaging/s3manager.spec \
    --noconfirm \
    --clean

if [ -d "dist/S3 Manager.app" ]; then
    echo ""
    echo "=== 빌드 성공 ==="
    echo "결과물: ${PROJECT_ROOT}/dist/S3 Manager.app"
    echo ""
    echo "실행 방법:"
    echo "  open '${PROJECT_ROOT}/dist/S3 Manager.app'"
    echo ""
    echo "또는 Applications 폴더로 복사:"
    echo "  cp -r 'dist/S3 Manager.app' /Applications/"
else
    echo ""
    echo "=== 빌드 실패 ==="
    echo "dist/S3 Manager.app 이 생성되지 않았습니다."
    exit 1
fi
