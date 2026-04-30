#!/usr/bin/env bash
# theme_radar 일일 파이프라인 — fetch → extract → catalysts → reports → wiki ingest
# Idempotent: 안전하게 여러 번 실행 가능 (이미 처리된 항목은 스킵)
#
# 사용법:
#   bash pipeline.sh                  # 전체 실행
#   bash pipeline.sh --skip-fetch     # 다운로드 스킵 (추출만)
#   bash pipeline.sh --skip-extract   # 추출 스킵
#   bash pipeline.sh --dry-run        # 실행 안 하고 plan만 출력
#
# 환경변수 (.env 또는 launchd plist에서):
#   OPENAI_API_KEY     — 추출용
#   WEBSHARE_PROXY_URL — YouTube 자막 다운로드용
#
# 종료 코드:
#   0  성공
#   1  치명적 오류 (API 키 부재 등)
#   2  부분 실패 (일부 stage 실패 그러나 계속 진행)

set -u  # undefined var은 오류, 단 set -e는 안 함 (한 stage 실패가 전체 중단 방지)

PIPELINE_VERSION="3.1.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
DATA="$ROOT/data/youtube"
LOG_DIR="$ROOT/logs"
TODAY=$(date +%Y%m%d)
LOG="$LOG_DIR/pipeline_$TODAY.log"

mkdir -p "$LOG_DIR"

# Source .env if exists (for credentials)
if [ -f "$ROOT/.env" ]; then
    set -a
    source "$ROOT/.env"
    set +a
fi

# ============================================================
# CHANNEL CONFIG — config.py의 CHANNELS dict가 단일 진실 원천
# ============================================================
# format: "channel_id:subdir:max_videos_per_run"
CHANNELS=()
while IFS= read -r line; do
    [ -n "$line" ] && CHANNELS+=("$line")
done < <(PYTHONPATH="$SCRIPTS" python3 -c '
from config import CHANNELS
for k, v in CHANNELS.items():
    cid = v["channel_id"]; mx = v["max_videos_per_run"]
    print(f"{cid}:{k}:{mx}")
')

if [ ${#CHANNELS[@]} -eq 0 ]; then
    echo "ERROR: config.py에서 CHANNELS 로드 실패" >&2
    exit 1
fi

# ============================================================
# OPTION PARSING
# ============================================================
SKIP_FETCH=false
SKIP_EXTRACT=false
SKIP_CATALYSTS=false
SKIP_REPORTS=false
SKIP_THEMES=false
SKIP_METHODOLOGY=false
SKIP_WIKI=false
SKIP_DASHBOARD=false
SKIP_LINT=false
SKIP_VALIDATION=false
DRY_RUN=false
FORCE_METHODOLOGY=false
LINT_APPLY=false
REEXTRACT_MISSING=""

for arg in "$@"; do
    case $arg in
        --skip-fetch) SKIP_FETCH=true ;;
        --skip-extract) SKIP_EXTRACT=true ;;
        --skip-catalysts) SKIP_CATALYSTS=true ;;
        --skip-reports) SKIP_REPORTS=true ;;
        --skip-themes) SKIP_THEMES=true ;;
        --skip-methodology) SKIP_METHODOLOGY=true ;;
        --skip-wiki) SKIP_WIKI=true ;;
        --skip-dashboard) SKIP_DASHBOARD=true ;;
        --skip-lint) SKIP_LINT=true ;;
        --skip-validation) SKIP_VALIDATION=true ;;
        --force-methodology) FORCE_METHODOLOGY=true ;;
        --lint-apply) LINT_APPLY=true ;;
        --reextract-missing=*) REEXTRACT_MISSING="${arg#--reextract-missing=}" ;;
        --dry-run) DRY_RUN=true ;;
    esac
done

# ============================================================
# HELPERS
# ============================================================
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
section() { log ""; log "=================="; log "$*"; log "=================="; }
fail_count=0
inc_fail() { fail_count=$((fail_count + 1)); }

# ============================================================
# PRE-FLIGHT
# ============================================================
section "🚀 theme_radar pipeline v$PIPELINE_VERSION started"
log "Today: $TODAY  |  Log: $LOG"

if [ "$DRY_RUN" = true ]; then
    log "DRY RUN — 다음 단계가 실행될 예정:"
    log "  1.  Fetch (skip=$SKIP_FETCH) — ${#CHANNELS[@]} channels"
    log "  2.  Extract (skip=$SKIP_EXTRACT) — gpt-5.4-nano"
    log "  3.  Catalysts (skip=$SKIP_CATALYSTS)"
    log "  4.  Reports (skip=$SKIP_REPORTS) — methodology, comparison"
    log "  4b. Theme Normalize + Pages (skip=$SKIP_THEMES)"
    log "  4c. Methodology Synth (skip=$SKIP_METHODOLOGY, force=$FORCE_METHODOLOGY)"
    log "  5.  Wiki Ingest (skip=$SKIP_WIKI)"
    log "  5b. Theme Dashboard (skip=$SKIP_DASHBOARD)"
    log "  5c. Lint Static (skip=$SKIP_LINT, apply=$LINT_APPLY)"
    log "  6.  Forward Validation (skip=$SKIP_VALIDATION) — prices·returns·scorecard"
    exit 0
fi

# Validate credentials
if [ "$SKIP_FETCH" = false ] && [ -z "${WEBSHARE_PROXY_URL:-}" ]; then
    log "ERROR: WEBSHARE_PROXY_URL not set (.env 또는 환경변수)"
    log "Skipping fetch stage."
    SKIP_FETCH=true
fi
if [ "$SKIP_EXTRACT" = false ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    log "ERROR: OPENAI_API_KEY not set"
    log "Skipping extract stage."
    SKIP_EXTRACT=true
fi

# ============================================================
# STAGE 0: REEXTRACT MISSING FIELD (선택)
# ============================================================
if [ -n "$REEXTRACT_MISSING" ]; then
    section "🧹 Stage 0: REEXTRACT MISSING ($REEXTRACT_MISSING)"
    cd "$SCRIPTS"
    if python3 reextract_missing_field.py --field="$REEXTRACT_MISSING" --apply >> "$LOG" 2>&1; then
        log "  ✓ 누락 필드 추출 파일 정리됨 — Stage 2에서 재추출"
    else
        log "  ✗ reextract_missing 실패"
        inc_fail
    fi
fi

# ============================================================
# STAGE 1: FETCH
# ============================================================
if [ "$SKIP_FETCH" = false ]; then
    section "📺 Stage 1: FETCH (incremental)"
    for entry in "${CHANNELS[@]}"; do
        IFS=':' read -r cid subdir max <<< "$entry"
        log "  Channel $subdir (max $max)..."
        cd "$SCRIPTS"
        if python3 yt_fetch_channel.py "$cid" "$subdir" "$max" >> "$LOG" 2>&1; then
            count=$(ls "$DATA/$subdir/transcripts/" 2>/dev/null | wc -l | tr -d ' ')
            log "  ✓ $subdir: $count total transcripts"
        else
            log "  ✗ $subdir: fetch failed (see log)"
            inc_fail
        fi
    done
else
    log "⏩ Stage 1 SKIPPED"
fi

# ============================================================
# STAGE 2: EXTRACT (idempotent — skips existing)
# ============================================================
if [ "$SKIP_EXTRACT" = false ]; then
    section "🤖 Stage 2: EXTRACT (gpt-5.4-nano)"
    for entry in "${CHANNELS[@]}"; do
        IFS=':' read -r cid subdir max <<< "$entry"
        T_DIR="$DATA/$subdir/transcripts"
        E_DIR="$DATA/$subdir/extractions_v2"
        if [ ! -d "$T_DIR" ] || [ -z "$(ls -A "$T_DIR" 2>/dev/null)" ]; then
            log "  ⏩ $subdir: no transcripts to extract"
            continue
        fi
        log "  Extracting $subdir..."
        cd "$SCRIPTS"
        if python3 yt_extract_batch.py gpt-5.4-nano "$T_DIR" "$E_DIR" >> "$LOG" 2>&1; then
            count=$(ls "$E_DIR" 2>/dev/null | wc -l | tr -d ' ')
            log "  ✓ $subdir: $count extracted"
        else
            log "  ✗ $subdir: extract had errors (see log)"
            inc_fail
        fi
    done
else
    log "⏩ Stage 2 SKIPPED"
fi

# ============================================================
# STAGE 3: CATALYSTS — youtube → catalysts.yaml
# ============================================================
if [ "$SKIP_CATALYSTS" = false ]; then
    section "📅 Stage 3: CATALYSTS (youtube_to_catalysts.py)"
    cd "$SCRIPTS"
    if python3 youtube_to_catalysts.py >> "$LOG" 2>&1; then
        log "  ✓ catalysts_from_youtube.yaml regenerated"
    else
        log "  ✗ catalysts conversion failed"
        inc_fail
    fi
    # Note: 머지는 수동 검토 후. 자동 머지는 별도 옵션으로.
else
    log "⏩ Stage 3 SKIPPED"
fi

# ============================================================
# STAGE 4: REPORTS — comparative methodology
# ============================================================
if [ "$SKIP_REPORTS" = false ]; then
    section "📊 Stage 4: REPORTS"
    cd "$SCRIPTS"
    if python3 yt_methodology_compare.py >> "$LOG" 2>&1; then
        log "  ✓ COMPARATIVE_METHODOLOGY.md regenerated"
    else
        log "  ✗ compare failed"
        inc_fail
    fi
    # 채널별 메소돌로지는 stage 4c (methodology_synth)가 담당. 단일 채널용 yt_methodology.py 폐기.
else
    log "⏩ Stage 4 SKIPPED"
fi

# ============================================================
# STAGE 4b: THEME NORMALIZE + PAGES (LLM-free)
# ============================================================
if [ "$SKIP_THEMES" = false ]; then
    section "🧭 Stage 4b: THEME NORMALIZE + PAGES"
    cd "$SCRIPTS"
    if python3 theme_normalizer.py >> "$LOG" 2>&1; then
        log "  ✓ theme_dictionary.json 갱신"
    else
        log "  ✗ theme_normalizer 실패"
        inc_fail
    fi
    if python3 theme_to_stock.py >> "$LOG" 2>&1; then
        log "  ✓ theme_to_stock_matrix.json 갱신"
    else
        log "  ✗ theme_to_stock 실패"
        inc_fail
    fi
    if python3 macro_event_classifier.py --vocab=macro >> "$LOG" 2>&1; then
        log "  ✓ macro_event_taxonomy.json 갱신"
    else
        log "  ✗ macro event classifier 실패"
        inc_fail
    fi
    if python3 macro_event_classifier.py --vocab=corporate >> "$LOG" 2>&1; then
        log "  ✓ corporate_event_taxonomy.json 갱신"
    else
        log "  ✗ corporate event classifier 실패"
        inc_fail
    fi
    if python3 validate_event_taxonomies.py --apply >> "$LOG" 2>&1; then
        log "  ✓ macro × corporate cross-axis 검증·정리"
    else
        log "  ✗ validate_event_taxonomies 실패"
        inc_fail
    fi
    if python3 regime_aligner.py >> "$LOG" 2>&1; then
        log "  ✓ regime_alignment.json (현재 regime vs theme의 macro 적합도)"
    else
        log "  ✗ regime_aligner 실패"
        inc_fail
    fi
    if python3 phase_mapper.py >> "$LOG" 2>&1; then
        log "  ✓ phase_mapping.json (macro→historical KB 카테고리 매핑)"
    else
        log "  ✗ phase_mapper 실패"
        inc_fail
    fi
    if python3 phase_tracker.py >> "$LOG" 2>&1; then
        log "  ✓ phase_tracking.json (theme별 현재 phase 추정)"
    else
        log "  ✗ phase_tracker 실패"
        inc_fail
    fi
    if python3 theme_pages_gen.py >> "$LOG" 2>&1; then
        log "  ✓ themes/*.md 갱신 (multi-axis events + 종목 섹션 포함)"
    else
        log "  ✗ theme_pages_gen 실패"
        inc_fail
    fi
else
    log "⏩ Stage 4b SKIPPED"
fi

# ============================================================
# STAGE 4c: METHODOLOGY SYNTH (LLM, 주 1회 게이트)
# ============================================================
if [ "$SKIP_METHODOLOGY" = false ]; then
    section "🧠 Stage 4c: METHODOLOGY SYNTH"
    cd "$SCRIPTS"
    METH_ARGS=""
    [ "$FORCE_METHODOLOGY" = true ] && METH_ARGS="--force"
    if python3 methodology_synth.py $METH_ARGS >> "$LOG" 2>&1; then
        log "  ✓ methodologies/*_pattern.md 갱신"
    else
        log "  ✗ methodology_synth 실패"
        inc_fail
    fi
    if python3 comparative_synth.py $METH_ARGS >> "$LOG" 2>&1; then
        log "  ✓ comparative_overview.md 갱신"
    else
        log "  ✗ comparative_synth 실패"
        inc_fail
    fi
else
    log "⏩ Stage 4c SKIPPED"
fi

# ============================================================
# STAGE 5: WIKI INGEST — theme_radar 갱신
# ============================================================
if [ "$SKIP_WIKI" = false ]; then
    section "📚 Stage 5: WIKI INGEST"
    if [ -f "$SCRIPTS/wiki_ingest.py" ]; then
        cd "$SCRIPTS"
        if python3 wiki_ingest.py >> "$LOG" 2>&1; then
            log "  ✓ theme_radar wiki updated"
        else
            log "  ✗ wiki ingest failed"
            inc_fail
        fi
    else
        log "  ⏩ wiki_ingest.py 미구현 (단계 스킵)"
    fi
else
    log "⏩ Stage 5 SKIPPED"
fi

# ============================================================
# STAGE 5b: THEME DASHBOARD (LLM-free)
# ============================================================
if [ "$SKIP_DASHBOARD" = false ]; then
    section "📡 Stage 5b: THEME DASHBOARD"
    cd "$SCRIPTS"
    if python3 theme_dashboard.py >> "$LOG" 2>&1; then
        log "  ✓ themes/_dashboard.md + index.md WEEKLY_PULSE 갱신"
    else
        log "  ✗ theme_dashboard 실패"
        inc_fail
    fi
    if python3 daily_digest.py --llm-summary >> "$LOG" 2>&1; then
        log "  ✓ today.md + daily/{date}.md (오늘의 한 페이지, LLM 1줄 요약 포함)"
    else
        log "  ✗ daily_digest 실패"
        inc_fail
    fi
else
    log "⏩ Stage 5b SKIPPED"
fi

# ============================================================
# STAGE 5c: LINT STATIC (LLM-free, broken/orphan/schema/gap/stale)
# ============================================================
if [ "$SKIP_LINT" = false ]; then
    section "🔎 Stage 5c: LINT STATIC"
    cd "$SCRIPTS"
    LINT_ARGS=""
    [ "$LINT_APPLY" = true ] && LINT_ARGS="--apply"
    if python3 lint.py $LINT_ARGS >> "$LOG" 2>&1; then
        log "  ✓ lint static 완료"
    else
        log "  ✗ lint 실패"
        inc_fail
    fi
    # Loop B: decision 인덱스 재구축 (idempotent — 새 backlink만 추가)
    if python3 decision_indexer.py --rebuild >> "$LOG" 2>&1; then
        log "  ✓ decision_indexer (Loop B: backlinks + citation_index)"
    else
        log "  ✗ decision_indexer 실패"
        inc_fail
    fi
else
    log "⏩ Stage 5c SKIPPED"
fi

# ============================================================
# STAGE 6: FORWARD VALIDATION (price fetch + returns + scorecard)
# ============================================================
if [ "$SKIP_VALIDATION" = false ]; then
    section "📈 Stage 6: FORWARD VALIDATION"
    cd "$SCRIPTS"
    if python3 price_fetcher.py --from-extractions >> "$LOG" 2>&1; then
        log "  ✓ price 캐시 갱신 (data/prices/)"
    else
        log "  ✗ price_fetcher 실패"
        inc_fail
    fi
    if python3 forward_validator.py >> "$LOG" 2>&1; then
        log "  ✓ forward_returns.json 갱신"
    else
        log "  ✗ forward_validator 실패"
        inc_fail
    fi
    if python3 scorecard.py >> "$LOG" 2>&1; then
        log "  ✓ scorecard.json + validation/scorecard.md 갱신"
    else
        log "  ✗ scorecard 실패"
        inc_fail
    fi
    if python3 auto_tune_weights.py >> "$LOG" 2>&1; then
        log "  ✓ channel_weights.json 자동 갱신 (Loop A: forward returns → weight)"
    else
        log "  ✗ auto_tune_weights 실패"
        inc_fail
    fi
    if python3 decay_robustness.py >> "$LOG" 2>&1; then
        log "  ✓ decay_analysis + robustness_analysis (시간축 + outlier 검증)"
    else
        log "  ✗ decay_robustness 실패"
        inc_fail
    fi
else
    log "⏩ Stage 6 SKIPPED"
fi

# ============================================================
# SUMMARY
# ============================================================
section "🏁 Pipeline complete"
log "Failures: $fail_count"
log "Log: $LOG"

# Status snapshot
log ""
log "=== 자산 현황 ==="
for entry in "${CHANNELS[@]}"; do
    IFS=':' read -r cid subdir max <<< "$entry"
    t=$(ls "$DATA/$subdir/transcripts/" 2>/dev/null | wc -l | tr -d ' ')
    e=$(ls "$DATA/$subdir/extractions_v2/" 2>/dev/null | wc -l | tr -d ' ')
    log "  $subdir: transcripts=$t, extractions=$e"
done

if [ $fail_count -gt 0 ]; then
    exit 2
else
    exit 0
fi
