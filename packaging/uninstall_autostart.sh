#!/usr/bin/env bash
# S3 Manager 자동 실행 해제 스크립트
set -euo pipefail

LABEL="ai.nota.s3manager"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
rm -f "$PLIST"

# 실행 중인 프로세스도 종료
pkill -f "S3 Manager.app/Contents/MacOS/s3manager" 2>/dev/null || true

echo "✅ 자동 실행 해제 완료 (LaunchAgent 제거)."
