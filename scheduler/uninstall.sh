#!/usr/bin/env bash
# theme_radar 자동화 제거

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
PLIST_NAME="com.${PROJECT_NAME}.daily"
TARGET_PLIST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

# Also try old name (backward compat)
OLD_PLIST="$HOME/Library/LaunchAgents/com.world_monitor.daily.plist"
if [ -f "$OLD_PLIST" ]; then
    launchctl unload "$OLD_PLIST" 2>/dev/null || true
    rm "$OLD_PLIST"
    echo "✓ 구 PLIST 제거: $OLD_PLIST"
fi

echo "=== theme_radar 자동화 제거 ==="

if [ -f "$TARGET_PLIST" ]; then
    launchctl unload "$TARGET_PLIST" 2>/dev/null || true
    rm "$TARGET_PLIST"
    echo "✓ 제거 완료: $TARGET_PLIST"
else
    echo "이미 제거됨 (또는 설치된 적 없음)"
fi

echo ""
echo "참고: 데이터·로그·스크립트는 그대로 보존됩니다."
echo "재설치: bash $(dirname \"$0\")/install.sh"
