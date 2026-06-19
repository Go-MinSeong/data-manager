#!/usr/bin/env bash
# Data Manager 자동 실행 설치 스크립트 (macOS LaunchAgent)
#
# 로그인 시 메뉴바에 항상 상주하도록 LaunchAgent를 등록한다.
#  - 로그인하면 자동 실행 (RunAtLoad)
#  - 크래시 시 자동 재시작 (KeepAlive: SuccessfulExit=false)
#  - 트레이 "종료"로 정상 종료(exit 0)하면 다음 로그인까지 재시작 안 함
#
# 사용법:
#   bash packaging/install_autostart.sh ["/Applications/Data Manager.app"]
#   (인자 생략 시 /Applications → ~/Applications → ./dist 순으로 탐색)

set -euo pipefail

LABEL="io.github.go-minseong.datamanager"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

# 1) .app 경로 결정
APP="${1:-}"
if [[ -z "$APP" ]]; then
  for cand in \
    "/Applications/Data Manager.app" \
    "$HOME/Applications/Data Manager.app" \
    "$(cd "$(dirname "$0")/.." && pwd)/dist/Data Manager.app"; do
    if [[ -d "$cand" ]]; then APP="$cand"; break; fi
  done
fi

if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "❌ Data Manager.app 을 찾을 수 없습니다."
  echo "   먼저 'bash packaging/build.sh' 로 빌드하거나, .app 경로를 인자로 주세요."
  exit 1
fi

EXEC="$APP/Contents/MacOS/s3manager"
if [[ ! -x "$EXEC" ]]; then
  echo "❌ 실행 파일이 없습니다: $EXEC"
  exit 1
fi

echo "▶ 대상 앱: $APP"

# 2) LaunchAgent plist 작성
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${EXEC}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/S3Manager.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/S3Manager.log</string>
</dict>
</plist>
PLISTEOF

echo "▶ LaunchAgent 작성: $PLIST"

# 3) 기존 등록 해제 후 재등록 (modern launchctl)
UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
launchctl enable "gui/${UID_NUM}/${LABEL}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true

echo "✅ 설치 완료. 지금 실행되었고, 앞으로 로그인 시 자동으로 메뉴바에 상주합니다."
echo "   로그: ~/Library/Logs/S3Manager.log"
echo "   해제: bash packaging/uninstall_autostart.sh"
