#!/usr/bin/env bash
# theme_radar 상태 점검 — 한눈에 시스템 건강 확인

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data/youtube"
VAULT="${VAULT:-$ROOT/vault}"  # config/project.yaml의 vault.path 또는 기본 ./vault
LOG_DIR="$ROOT/logs"

echo "=========================================="
echo "  theme_radar STATUS — $(date)"
echo "=========================================="
echo ""

# 1. launchd 상태
echo "🤖 자동화 상태:"
if launchctl list | grep -q com.theme_radar.daily; then
    pid=$(launchctl list | grep com.theme_radar.daily | awk '{print $1}')
    echo "  ✅ launchd agent active (last PID: $pid)"
else
    echo "  ❌ launchd agent 미설치 (bash scheduler/install.sh)"
fi
echo ""

# 2. 채널별 자산 현황
echo "📺 채널별 자산:"
printf "  %-15s %-10s %-10s %-15s\n" "Channel" "Trans" "Extract" "Last Updated"
printf "  %-15s %-10s %-10s %-15s\n" "-------" "-----" "-------" "-----------"
for dir in han_gyunsoo 86bunga seo_jaehyung supergaemi; do
    t_count=$(ls "$DATA/$dir/transcripts/" 2>/dev/null | wc -l | tr -d ' ')
    e_count=$(ls "$DATA/$dir/extractions_v2/" 2>/dev/null | wc -l | tr -d ' ')
    last=$(ls -t "$DATA/$dir/extractions_v2/"*.json 2>/dev/null | head -1 | xargs -I{} basename {} 2>/dev/null | cut -c1-8)
    printf "  %-15s %-10s %-10s %-15s\n" "$dir" "$t_count" "$e_count" "${last:-N/A}"
done
echo ""

# 3. 최근 파이프라인 로그
echo "📋 최근 파이프라인 로그 (마지막 3개):"
ls -t "$LOG_DIR/pipeline_"*.log 2>/dev/null | head -3 | while read f; do
    name=$(basename "$f")
    last=$(tail -1 "$f" 2>/dev/null | cut -c1-80)
    echo "  $name: $last"
done
echo ""

# 4. theme_radar wiki 상태
echo "📚 theme_radar wiki:"
if [ -d "$VAULT" ]; then
    pages=$(find "$VAULT" -name "*.md" | wc -l | tr -d ' ')
    echo "  ✅ Vault: $pages markdown pages"
    if [ -f "$VAULT/log.md" ]; then
        last_ingest=$(grep -E "^### .* — INGEST" "$VAULT/log.md" 2>/dev/null | head -1)
        echo "  Last ingest: ${last_ingest:-N/A}"
    fi
else
    echo "  ❌ Vault not found at $VAULT"
fi
echo ""

# 5. catalysts.yaml 상태
CATALYSTS="${CATALYSTS_YAML:-}"  # config 의 integrations.geopolitical_investor.catalysts_yaml
if [ -f "$CATALYSTS" ]; then
    total=$(grep -c "^- id:" "$CATALYSTS" 2>/dev/null)
    yt=$(grep -c "^  source: youtube_extraction" "$CATALYSTS" 2>/dev/null)
    echo "📅 catalysts.yaml:"
    echo "  Total: $total catalysts"
    echo "  YouTube origin: $yt"
fi
echo ""

# 6. 다음 실행 시각
echo "⏰ 다음 자동 실행:"
next=$(date -v+1d -v6H -v0M -v0S "+%Y-%m-%d 06:00:00" 2>/dev/null || date -d "tomorrow 06:00" 2>/dev/null)
echo "  매일 06:00  (다음: $next)"
echo ""
echo "=========================================="
