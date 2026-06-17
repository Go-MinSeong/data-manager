#!/usr/bin/env bash
# Data Manager 빌드 스크립트
#
# 사용법:
#   cd /path/to/s3-manager
#   bash packaging/build.sh
#
# 빌드 순서:
#   1. 프론트엔드(React) 빌드 → frontend/dist/
#   2. 아이콘 생성 (assets/app_icon.icns 없으면)
#   3. PyInstaller → dist/Data Manager.app
#
# 요구사항:
#   - Node.js + npm (프론트엔드 빌드)
#   - uv (Python 패키지 관리)
#   - Python 3.12 (venv에 pyinstaller, pywebview, pystray 포함)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Data Manager 빌드 시작 ==="
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

# iconutil 로 고품질 .icns 재생성 (macOS 전용).
# dock 아이콘이 최신 디자인을 반영하도록 컬러 app_icon.png에서 매번 iconset을 재생성한다.
# (이전엔 캐시된 iconset/모노크롬 tray에서 만들어 dock 아이콘이 갱신되지 않았음)
if command -v iconutil &> /dev/null && command -v sips &> /dev/null && [ -f "assets/app_icon.png" ]; then
    ICONSET_DIR="assets/app_icon.iconset"
    rm -rf "${ICONSET_DIR}"
    mkdir -p "${ICONSET_DIR}"
    for size in 16 32 128 256 512; do
        sips -z "${size}" "${size}" "assets/app_icon.png" \
            --out "${ICONSET_DIR}/icon_${size}x${size}.png" > /dev/null 2>&1
        d2=$((size * 2))
        sips -z "${d2}" "${d2}" "assets/app_icon.png" \
            --out "${ICONSET_DIR}/icon_${size}x${size}@2x.png" > /dev/null 2>&1
    done
    iconutil -c icns "${ICONSET_DIR}" -o "assets/app_icon.icns" && \
        echo "iconutil 로 .icns 재생성 완료 (컬러 app_icon.png 기반)" || \
        echo "경고: iconutil 실패, PIL 생성 .icns 사용"
fi

# ------------------------------------------------------------------ #
#  3. PyInstaller 빌드                                                  #
# ------------------------------------------------------------------ #
echo ""
echo "--- [3/4] PyInstaller 빌드 ---"

# 아키텍처 (기본 arm64). universal2는 python.org universal2 Python에서만 가능:
#   S3M_ARCH=universal2 bash packaging/build.sh
ARCH="${S3M_ARCH:-arm64}"
echo "타깃 아키텍처: ${ARCH}"

# pyinstaller 보장: 'uv run pyinstaller'는 실행 직전 venv를 동기화하며
# (base 의존성이 아닌) pyinstaller를 제거한다. 따라서 venv에 설치 후
# venv의 pyinstaller 바이너리를 직접 호출한다.
uv pip install pyinstaller >/dev/null 2>&1 || true
PYI="${PROJECT_ROOT}/.venv/bin/pyinstaller"
if [ ! -x "${PYI}" ]; then
    echo "오류: ${PYI} 가 없습니다. 'uv venv --python 3.12 && uv pip install -e . pyinstaller' 후 재시도."
    exit 1
fi

rm -rf build dist
S3M_ARCH="${ARCH}" "${PYI}" packaging/s3manager.spec --noconfirm --clean

if [ ! -d "dist/Data Manager.app" ]; then
    echo ""
    echo "=== 빌드 실패 ==="
    exit 1
fi

# ------------------------------------------------------------------ #
#  4. 코드서명(ad-hoc) + 배포용 zip                                     #
# ------------------------------------------------------------------ #
echo ""
echo "--- [4/4] 서명 + 패키징 ---"

# ad-hoc 서명: 서명 없는 .app은 일부 환경에서 "손상됨"으로 실행이 막힌다.
# (정식 Developer ID 서명/공증이 아니므로 다운로드본은 여전히 Gatekeeper 경고 → INSTALL.md)
codesign --force --deep --sign - "dist/Data Manager.app" 2>/dev/null \
    && echo "ad-hoc 서명 완료" || echo "경고: codesign 실패(서명 없이 진행)"

# 배포용 zip (ditto로 번들 메타데이터/심볼릭링크 보존)
ZIP="dist/Data-Manager-${ARCH}.zip"
rm -f "${ZIP}"
ditto -c -k --sequesterRsrc --keepParent "dist/Data Manager.app" "${ZIP}"

echo ""
echo "=== 빌드 성공 ==="
echo "  앱:  ${PROJECT_ROOT}/dist/Data Manager.app"
echo "  zip: ${PROJECT_ROOT}/${ZIP}   ← 이 파일을 동료에게 전달"
echo ""
echo "받는 사람 설치: INSTALL.md 참고 (압축 해제 → /Applications 이동 → 첫 실행 시 우클릭 '열기')"
