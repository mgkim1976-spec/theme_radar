#!/usr/bin/env bash
# theme_radar 자동화 설치 스크립트
# launchd agent를 ~/Library/LaunchAgents에 등록 + 활성화
#
# 사용법: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
PLIST_NAME="com.${PROJECT_NAME}.daily"
SOURCE_PLIST_TEMPLATE="$SCRIPT_DIR/com.theme_radar.daily.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/${PLIST_NAME}.plist"

# Generate plist with current PROJECT_ROOT (relocatable)
SOURCE_PLIST="/tmp/${PLIST_NAME}.plist"
sed -e "s|@@PROJECT_ROOT@@|$PROJECT_ROOT|g" \
    -e "s|@@PLIST_LABEL@@|$PLIST_NAME|g" \
    -e "s|@@HOME@@|$HOME|g" \
    "$SOURCE_PLIST_TEMPLATE" > "$SOURCE_PLIST"

echo "=== theme_radar 자동화 설치 ==="
echo ""

# Pre-flight checks
if [ ! -f "$SOURCE_PLIST" ]; then
    echo "❌ Source plist not found: $SOURCE_PLIST"
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "⚠️  .env 파일 없음. 샘플 생성 권장:"
    echo "   cp $PROJECT_ROOT/.env.example $PROJECT_ROOT/.env"
    echo "   nano $PROJECT_ROOT/.env"
    echo ""
    read -p "그래도 진행할까요? (y/N): " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

# Unload if already loaded (재설치 안전)
if launchctl list | grep -q "$PLIST_NAME"; then
    echo "기존 agent 언로드 중..."
    launchctl unload "$TARGET_PLIST" 2>/dev/null || true
fi

# Copy plist
mkdir -p "$TARGET_DIR"
cp "$SOURCE_PLIST" "$TARGET_PLIST"
echo "✓ plist 복사: $TARGET_PLIST"

# Load
launchctl load "$TARGET_PLIST"
echo "✓ launchctl load 완료"

# Verify
if launchctl list | grep -q "$PLIST_NAME"; then
    echo ""
    echo "✅ 설치 완료. PLIST: $PLIST_NAME — 다음 실행: 매일 06:00"
    echo ""
    echo "유용한 명령:"
    echo "  상태 확인:        launchctl list | grep $PLIST_NAME"
    echo "  지금 즉시 실행:    launchctl start $PLIST_NAME"
    echo "  로그 보기:        tail -f $PROJECT_ROOT/logs/pipeline_\$(date +%Y%m%d).log"
    echo "  제거:            bash $SCRIPT_DIR/uninstall.sh"
else
    echo "❌ 설치 실패 — launchctl list에 등록 안 됨"
    exit 1
fi
