# theme_radar — Changelog

## v3.0.0 — 2026-04-28 (Index-relative Alpha — 시기 효과 제거)

### 문제 인식
- 채널별 데이터 기간이 다름 (86bunga 2020-2023 약세장 포함, seo_jaehyung 2024-2026 강세장)
- raw return으로 채널 비교 시 시기 효과(시장 베타)가 chiefly 반영됨
- seo_jaehyung +37.5%(90d) 중 25%p가 KOSPI 베타. 진짜 alpha는 +12.3%

### Added — Index-relative Alpha
- **`forward_validator.py`**: 각 ticker forward return 옆에 **alpha (= ticker_return − benchmark_return)** 자동 계산
  - Benchmark: `KRX → 069500 (KODEX 200)` / `US → SPY`
  - 출력: `forward_returns.json` 의 returns dict 에 `alpha_7d/30d/60d/90d` 추가
- **`scorecard.py`**: `mean_alpha`, `win_rate_alpha`, `median_alpha` 집계 추가
  - 모든 group (channel/event_type/canonical_theme/signal/market) 에 alpha 컬럼
  - 표는 alpha 기준 정렬 (raw 표시는 참고용)
- **`auto_tune_weights.py`**: alpha 기반 가중치 산출로 전환 (raw fallback 가능)
  - bonus = max(0, mean_alpha) × scale, penalty = mean_alpha 음수 강도에 비례

### 데이터 충격 — 채널 평가 완전 재정렬

| 채널 | Raw 30d | **Alpha 30d** | Alpha 30d win | weight v2.5 → v3.0 |
|---|---:|---:|---:|---|
| seo_jaehyung | +11.1% | **+2.4%** (90d +12.3%) | 57% | 1.55 → **1.37** |
| 86bunga | +2.6% | **+0.7%** (90d +1.7%) | 48% | 0.70 → **1.05** ↑ |
| han_gyunsoo | +2.3% | **−5.7%** (90d −28.3%) | **33%** | 0.70 → **0.60** ↓ |

**핵심 발견**:
- **86bunga**: raw 약했지만 *alpha 양수*. 약세장 포함 시기에 KOSPI 대비 outperform → 진짜 가치투자 능력
- **han_gyunsoo**: raw 양수였지만 *alpha −28.3%* (90d). 시장 따라가기만 했어도 훨씬 좋았을 → 시장 대비 underperformer
- **seo_jaehyung**: raw 압도적이었지만 alpha는 절반. 베타 영향 큼. 그래도 1위

### Changed — 페이지 통합
- youtuber 페이지 Forward Validation 섹션: raw + alpha 동시 표시 (alpha 강조)
- theme 페이지 동일
- methodology_synth Loop D 프롬프트 alpha 우선 → LLM이 "alpha 기준 시장 대비 outperform/underperform" 톤으로 합성
  - 86bunga 합성 결과: "7d alpha −0.74%로 단기는 못 따라가, 30d+0.69% / 60d+2.10% / 90d+1.70%로 중기에서 시장 베타 상회"

### Why
- v2.x까지: raw return 기반 평가 → 시기 효과로 왜곡
- v3.0: alpha 기반 평가 → **시기 다른 채널 공정 비교 가능**, 진짜 alpha-generating channel 식별

## v2.6.0 — 2026-04-28 (Daily Digest — "오늘의 한 페이지")

### Added
- **`daily_digest.py`** 신설 — 매일 아침 한 페이지 요약 자동 생성:
  - 어제 archive (`daily/{yesterday}.md`) 와 비교 → 오늘 NEW만 highlight
  - 단계별 delta: 신규 emerging / 가속 진입 / 합의 강화 / 새 fading
  - 매크로 환경 (regime · 4채널 best/worst · 가중치 변화)
  - 우선 읽기 (citation_index high-signal 페이지)
  - 옵션 LLM 1줄 요약 (~$0.001/일)
- **`theme_dashboard.py` JSON 출력** — `data/reference/compiled/dashboard_signals.json` 자동 생성 (daily_digest가 소비)
- **출력**:
  - `VAULT/today.md` — 항상 오늘 (덮어쓰기)
  - `VAULT/daily/{YYYY-MM-DD}.md` — 일자별 아카이브 (delta 계산용 frontmatter 포함)
- pipeline stage 5b 통합: theme_dashboard 다음 자동 실행 (`--llm-summary` 활성)

### Why
- v2.5까지: dashboard에 모든 단계별 테마 누적 표시. 그러나 *오늘* 무엇이 새로 발생했는지 한눈에 안 보임
- v2.6: **매일 아침 today.md 한 페이지만 열면 충분** — Karpathy 비전의 사용자 인터페이스 완성

### 첫 실행 결과
- 오늘 NEW emerging 102 (첫 실행이라 모두 신규로 표시; 내일부터 진짜 delta)
- LLM 요약: "현재 OVERHEATING regime에서 emerging 102개 유지, 가속 진입 0, fading 140으로 모멘텀 일부 약화 가능"
- 비용: $0.0008 (LLM 1줄 요약)

## v2.5.0 — 2026-04-28 (Phase 1 정리 + Phase 2 regime/phase 통합)

### Phase 1 — 외국주 매핑 + Lint 정리
- **외국주 alias 30+ 추가** (SMIC, IONQ, 메이시스, 마벨테크, 카니발, 보스턴 다이내믹스 등)
  - 매핑률 80.6% → **81.3%** (사적기업·delisted 위주가 잔여)
- **`lint_resolver` stub 생성 시 type별 필수 frontmatter 모두 채움**
- 기존 stub 18개 frontmatter backfill
- **lint findings 156 → 11 (-93%)** — broken_link 5 + schema_drift 5 + orphan 1만 잔여 (대부분 의도된 placeholder)

### Phase 2 — Regime + Phase 통합 (Path 1 #7 #8)
- **`sync_vocabularies` registry 확장**:
  - `regime_state.snapshot.json` — investment_ontology 의 SIGNAL-REGIME.md frontmatter parse → JSON
  - `phase_kb.snapshot.json` — macro_events_driven_investments 의 30 historical events × 6-phase KB
- **`regime_aligner.py`** 신설:
  - 각 macro-매칭 theme의 event `regime_context` vs 현재 regime 자동 비교
  - alignment: aligned ✅ / partial 🟡 / misaligned 🔴 / neutral ⚪
  - 출력: `data/reference/compiled/regime_alignment.json`
- **`phase_mapper.py`** 신설:
  - macro_event subject_category → historical category 큐레이션 매핑
  - 모든 42 macro events에 historical event 매칭 (카테고리 + 키워드 fuzzy)
  - 출력: `data/reference/compiled/phase_mapping.json`
- **`theme_pages_gen` Event Classification (multi-axis) 4축 확장**:
  ```
  - 🌐 Macro: real_rate_surge · severity=HIGH
  - 🏢 Corporate: earnings_miss · severity=HIGH
  - 🌡️ Regime: 현재 OVERHEATING · 적합도 ⚪ neutral (regime_context 없음)
  - ⏱️ 유사 historical: iraq_war_2003 (2003-03, 전쟁/지정학)
  ```
- **pipeline stage 4b 확장**: classifier 2개 → validate → **regime_aligner** → **phase_mapper** → theme_pages_gen
- **현재 시점 데이터**:
  - 현재 regime: **OVERHEATING** (FRED z-score 기반, score=+0.037, confidence=68%)
  - macro-매칭 743 themes 중 misaligned 165, neutral 578 (대부분 macro events에 regime_context 미정의)

### Why
- v2.4까지: 4 loops 닫혔으나 다차원 분류 (macro·corporate)만
- v2.5: **시간축(phase) + 환경축(regime)** 추가 → 테마가 *언제* (시간) *어떤 환경에서* (regime) 적합한지 자동 표시
- knowledge graph가 더 풍부해짐. cross-project vocabulary 재사용으로 비용 0.

## v2.4.0 — 2026-04-28 (Loop B + C + D — Karpathy compounding 본격 가동)

### Loop B — Query 결과의 wiki 환류
- **`decision_indexer.py`** 신설 — query.py가 decision 저장 직후 자동 호출:
  - 인용된 source 페이지 각각에 `AUTO_DECISION_LINKS` 백링크 자동 추가
  - `data/reference/compiled/citation_index.json` 갱신 (자주 인용되는 페이지 = high-signal)
  - `--rebuild` 로 전수 재구축 (idempotent)
- query.py 통합: 답변 저장 후 자동 backlink + citation 카운트
- pipeline stage 5c 통합: 매일 idempotent rebuild

### Loop C — Lint 자동 해결
- **`lint_resolver.py`** 신설 — questions/ 자동 처리:
  - **broken_link**: LLM이 의도 파악 → 가까운 슬러그로 자동 fix 또는 stub 페이지 생성
  - **schema_drift**: frontmatter 누락 필드 자동 추가 (heuristic)
- `vault_utils` 폴더 처리 분리:
  - `IGNORE_DIRS` = .obsidian / _attachments (전 영역 무시)
  - `IGNORE_FOR_BODY_PROCESSING` = + _templates / _schema (본문 처리만 무시, 존재 체크엔 포함)
  - `extract_wikilinks` table escape `\\|` 처리 (slug 추출 정확도)
- **첫 실행 효과**: 73 questions → 71 자동 해결 시도 (10 fix + 56 stub + 1 schema). lint findings 156 → **29** (-81%).

### Loop D — methodology_synth 데이터 검증 톤
- `methodology_synth.py` 프롬프트에 **forward returns 메타 자동 주입**:
  - 채널별 7d/30d/60d/90d mean·win_rate·median 통계 그대로 제공
  - LLM이 "데이터 검증" 섹션을 정확한 숫자 인용으로 합성
  - 가설-데이터 충돌 시 "데이터로는 약함" 톤으로 솔직히 명시
- 첫 실행 (seo_jaehyung): "Forward Validation에서 7d +2.76% → 90d +37.49% (win 84.8%) ... 산업 사이클 테마가 중기 추세에서 실효" 톤으로 합성됨
- 비용: $0.0008/회 (변동 거의 없음)

### Why
- v2.3까지 Loop A 1개만 닫혔음 (forward → weight)
- v2.4에서 3개 추가 closure → **4개 loop 모두 가동**:
  - A. forward → weight (auto)
  - B. query → wiki backlinks (auto via query.py)
  - C. lint → questions/ → 자동 해결 (CLI + 매일 rebuild)
  - D. methodology synth ← forward returns (자동)
- *진짜* Karpathy LLM Wiki: knowledge accumulation → **knowledge compounding** 단계 진입.

## v2.3.0 — 2026-04-28 (Loop A closure + Portability)

### Loop A — Auto stock_weight feedback (closed loop)
- **`auto_tune_weights.py`** — forward returns 기반 채널 가중치 자동 산출
  - 윈도우 자동 선택 (90d > 60d > 30d, n ≥ 30 첫 번째 사용)
  - 룰: `weight = 1.0 + max(0, mean - market_baseline)*scale - penalty`, clamp [0.3, 2.0]
  - 윈도우별 baseline·scale 캘리브레이션 (30d=0.04/5×, 60d=0.07/3.5×, 90d=0.10/2×)
  - 출력: `data/reference/compiled/channel_weights.json` (delta 추적 포함)
- **`theme_to_stock.py`** — `channel_weights.json` 우선 사용, 없으면 config 기본값 fallback
- **pipeline stage 6 통합** — scorecard 다음 자동 호출
- 첫 실행 결과: seo_jaehyung 1.55 (90d, mean=37.5%, win=85%) · 86bunga 0.70 · han_gyunsoo 0.70 · supergaemi 1.20 (n부족)
- **이게 진짜 closed loop**: 매주 가격 갱신 → 가중치 자동 재조정 → matrix 재계산. 사용자 개입 0.

### Portability — yaml 외부화 + 신규 사용자 부트스트랩
- **`config/` 디렉터리** 신설:
  - `channels.yaml` — 추적 채널 (CHANNELS dict 외부화)
  - `project.yaml` — VAULT 경로·region·integrations
  - `lens_presets.yaml` — lens별 기본값
  - `channels.example.txt` — 입력 형식 예시
- **`scripts/config.py` 로더화** — yaml 우선, defaults fallback (backward compat 100%)
- **`scripts/init_project.py`** 신설 — 신규 사용자 5분 부트스트랩:
  - `--channels=file.txt` 일괄 채널 등록 + 검증
  - `--add UC...:subdir:lens` 단일 추가
  - `--vault=path --region=KR` project.yaml 갱신
  - 인터랙티브 모드 (인자 없으면 stdin 읽음)
  - 데이터 디렉터리 자동 생성
- **`QUICKSTART.md`** 신설 — 5단계 가이드 (다른 사용자가 자기 채널 리스트로 시작)
- **외부 통합 옵션화** — `integrations.geopolitical_investor.enabled` / `vocabulary_snapshots.enabled` 로 끄기 가능

### Why
- v1-v2.2 누적 검증: 개별 사용자 종속 (mg_mac/ 하드코딩 경로, 4채널 고정)
- v2.3에서 portability 확보 → 다른 사람이 자기 정보 소스로 같은 시스템 가동 가능
- Loop A로 "가격 데이터 → 가중치 → 매트릭스" 사이클 완성. Karpathy 패턴의 "knowledge compounding" 본격 가동.

## v2.2.0 — 2026-04-28 (외국주 매핑 보강 + multi-axis event 분류)

### Added — 외국주 매핑 보강
- `price_fetcher.py` 의 alias 사전 확장:
  - 외국주 unique 매칭: 30 → **216** (마벨, MP, 폭스바겐, 텐센트뮤직, 코인베이스, 모건스탠리, ARM 등 60+ 추가)
  - KRX 통상명: LNF/L&F → 엘앤에프, 메리츠지주/금융그룹, JYP/SM/HYBE 그룹 변형, 빅히트 표기 변형 등
- mention 매핑률 75% → **80.6%** (US 3,266 mentions 추가 매핑)

### Added — Multi-axis Event 분류 (Path 1 #3, #4)
- **`corporate_event_vocabulary.snapshot.json`** snapshot — investment_ontology 의 79 기업 이벤트 vendoring (sync_vocabularies registry 등록)
- **`macro_event_classifier.py` 일반화** — `--vocab=macro|corporate` CLI 인자로 두 vocabulary 모두 처리. snapshot/cache/output path 자동 분기
- **`themes/{slug}.md` Event Classification (multi-axis) 섹션** 추가:
  ```
  - 🌐 Macro: fed_pivot · conf=high
  - 🏢 Corporate: earnings_beat · conf=medium
  ```
- **pipeline stage 4b 확장** — macro·corporate classifier 순차 실행 후 theme_pages_gen
- **분류 결과**:
  - macro: 865 themes (22.5%) — fed_pivot 244, us_china_decoupling 112, erp_compression 94 ...
  - corporate: 1,416 themes (37%) — fda_approval 298, earnings_miss 147, earnings_beat 118 ...
  - 양쪽 매칭: 363 (중첩 9.4%, 일부는 false positive — Stage B LLM으로 정리 가능)

### Added — Cross-axis Validation
- **`validate_event_taxonomies.py`** — macro × corporate 동시 매칭의 false positive 정리:
  - heuristic 1: macro=high · corp=medium → corp 매칭 제거
  - heuristic 2: macro=medium · corp=high → macro 매칭 제거
  - heuristic 3: macro=high · corp=high → 양쪽 보존 (legitimate dual-axis)
  - LLM (medium × medium 184건만): "어느 쪽이 적절한가? 또는 둘 다 / 둘 다 아닌가?"
- pipeline stage 4b 끝부분에 자동 통합

### Validation 효과 (실제 측정)
- cross-axis 매칭: 363 → **31** (-91%)
- corporate 매칭: 1,416 → 1,193 (false 223건 제거)
- macro 매칭: 865 → 743 (false 122건 제거)
- LLM verdict 분포: macro 143 / corporate 17 / none 13 / both 11
- **총 비용 $0.0015** (heuristic 무료 + LLM 4 calls)

### Note (다음 iteration)
- regime conditioning (#7) + phase tracking (#8) 은 별도 ticket — investment_ontology 의 regime_detector / macro_events_driven_investments 의 event_playbook 동적 호출 패턴 필요

## v2.1.0 — 2026-04-28 (데이터 검증 적용 + 폴더 정리 + Quick wins)

### Changed (data-driven)
- **`config.CHANNELS.stock_weight` 데이터 기반 재조정** — v2.0 forward_returns 기반:
  - seo_jaehyung 0.7 → 1.3 (90d +37.6%, win 72%)
  - 86bunga 0.6 → 0.5 (90d +2.7%, 시장 평균)
  - han_gyunsoo 0.8 → 0.7 (win 48%)
  - supergaemi 1.2 (유지, 데이터 부족)
- **`theme_to_stock_matrix` 가중치 갱신** — 545 페이지 재계산

### Added — 페이지 통합
- **youtuber 페이지** Forward Validation 섹션 (channel별 7d/30d/60d/90d)
- **theme 페이지** Forward Validation 섹션 (canonical theme별)

### Quick Wins (#1·#2)
- **#1**: `pipeline.sh` stage 4의 `yt_methodology.py` 호출 제거 (대체된 데드 코드, 매일 거짓 실패 로그)
- **#2**: `data/reference/` 재구조화:
  - `data/reference/` (정적 reference): krx_tickers, ticker_alias, vocabularies/
  - `data/reference/compiled/` (재생성 artifact): theme_dictionary, theme_to_stock_matrix, forward_returns, scorecard, macro_event_taxonomy, lifecycle_thresholds, vault_index
  - `data/reference/cache/` (LLM 캐시 영구 보존): theme_tags_cache, macro_event_llm_cache
  - 12개 모듈의 path constants 갱신, .gitignore에 `compiled/` + `data/prices/` 추가

## v2.0.0 — 2026-04-28 (Forward Validation Loop — 가격 피드백)

### Added
- **`price_fetcher.py`** — KRX + 주요 외국주 가격 캐시. FinanceDataReader 백엔드. 증분 갱신.
  - 한국 통상명 (네이버, LIG넥스원, 메리츠증권 등) 약 60개 lookup 보강
  - 외국주 alias map ~70개 (테슬라→TSLA, 엔비디아→NVDA, 마이크론→MU, ...)
  - 인덱스 ETF (S&P500→SPY, 나스닥→QQQ)
  - `--from-extractions` 추출에서 자동 ticker 수집
- **`forward_validator.py`** — (theme, ticker, mention_date) → 7d/30d/60d/90d 수익률
  - 거래일 nearest 매칭, 미완료 윈도우는 None
  - `data/reference/forward_returns.json`
- **`scorecard.py`** — channel·event_type·canonical_theme·signal·market 별 통계
  - mean_return, median, win_rate, n_observations
  - `data/reference/scorecard.json` + `VAULT/validation/scorecard.md`
- **(v1.7) `macro_event_classifier.py` Stage B** — LLM fallback로 키워드 매칭 미스 보완 ($0.0014). high-mention 매칭률 37%→63%.
- **(v1.7) `sync_vocabularies.py` + macro_event_vocabulary snapshot** — investment_ontology의 42 매크로 이벤트 vocabulary를 cross-project 의존성 없이 재사용 (snapshot 패턴).
- **`comparative_synth.py` (v1.4)** + 기타 v1.4-1.6 항목은 별도 엔트리 참조.

### Pipeline
- **stage 6 (FORWARD VALIDATION)** 신설 — price fetch → forward returns → scorecard. 매일 cascade.
- 버전 1.6.0 → 2.0.0

### Why
- v1.x까지 시스템은 *그럴듯한* 분류·합성을 만들어내지만 *실제 수익에 기여하는지* 확인 불가
- v2.0의 forward validation으로 채널별 stock_weight·methodology synth·event_type 분류가 데이터 기반으로 재조정 가능해짐
- catalyst_driven_trading의 win_rate / tier 패턴 차용

## v1.6.0 — 2026-04-28 (Karpathy Wiki 패턴 — Query + Lint workflow)

### Added — Query Workflow
- **`query.py`** — 사용자 질문을 vault 기반으로 답변. 2-stage LLM:
  - Router (gpt-5.4-nano): 질문 + 페이지 인덱스 → 관련 슬러그 5-10개
  - Synthesizer: 질문 + 라우팅 페이지 풀텍스트 → 인용 포함 마크다운 답변
- 답변은 `decisions/{YYYYMMDD}_{slug}.md`로 자동 저장 (출처·메타·비용 포함). 향후 같은 질문은 캐시 활용 가능.
- 비용 회당 ~$0.003 (실측). `--top=N` 라우팅 페이지 수, `--no-save` 저장 안 함.

### Added — Lint Workflow (Static Pass)
- **`lint.py`** — vault 정합성 자동 검사 (LLM 미사용):
  - `broken_link`: `[[slug]]`가 vault에 없는 페이지를 참조
  - `orphan`: 어떤 페이지도 참조하지 않는 페이지 (auto-ingested 자동 면제)
  - `schema_drift`: frontmatter 필수 필드 누락 (type별 정의)
  - `dictionary_gap`: multi-mention ≥10 인데 page 없음
  - `stale_methodology`: 30일+ 미갱신
- 기본 dry-run, `--apply`로 `questions/{date}_{cat}_{slug}.md` 자동 등록.

### Added — Shared Util
- **`vault_utils.py`** — page iter, frontmatter parse, [[wikilink]] 추출, slug 매칭. 이후 모든 vault-side 도구의 기반.

### Pipeline
- **stage 5c (LINT STATIC)** 추가 — 매일 자동 실행, 비용 0. `--skip-lint` `--lint-apply` 플래그.
- 버전 1.5.0 → 1.6.0

### Validation
- 첫 lint run: 546 페이지 검사, **156 findings** (broken_link 151, schema_drift 5). orphan 489건은 auto-ingested 면제 룰로 정상 필터링.
- 첫 query test: "한균수와 86번가의 원전 view 차이?" → router가 정확히 youtubers·methodologies·themes 페이지 8개 라우팅, synth가 cite 포함 4-step 답변 생성, 총 비용 $0.0027.

### Why
- v1.5까지 시스템은 **knowledge accumulation** (데이터 쌓기)에 머물렀음. v1.6의 Query·Lint가 **knowledge compounding** (재사용·자기 검증)을 가능하게 함. Karpathy LLM Wiki의 본질적 가치 발현.

## v1.5.0 — 2026-04-27 (스키마 마이그레이션 + 동적 lifecycle)

### Added
- **`reextract_missing_field.py`** — 스키마 누락 필드(예: `event_type`) 검출 후 해당 추출만 삭제 → idempotent 재추출 유도. 기본 dry-run, `--apply`로 실제 삭제. 채널·필드 단위 필터.
- **pipeline.sh `--reextract-missing=<field>` 플래그** — Stage 0에서 자동 정리 후 Stage 2 재추출. 예: `bash pipeline.sh --reextract-missing=event_type`.
- **`lifecycle.py` 모듈** — 데이터 분포 기반 동적 lifecycle 임계값:
  - `emerging_window` = p20(days_since_first), 7-21일 floor·cap
  - `fading_threshold` = p70(days_since_last), 30-180일 floor·cap
  - `mature_min_age` = p50(days_since_first), 60-365일 floor·cap
  - 캐시: `data/reference/lifecycle_thresholds.json`
  - `theme_pages_gen` + `theme_dashboard` 공유

### Changed
- **`theme_pages_gen` / `theme_dashboard`** — 정적 7일/30일/45일 하드코딩 제거. lifecycle.py가 산출한 임계값 사용. 기존 페이지/대시보드 자동 재계산.
- 4채널 데이터 분포 결과: emerging≤21d, fading≥180d, mature≥365d (86번가 2020년 데이터로 p50/p70이 큼 → cap에 클램프).

### Why
- 정적 임계값은 시장 변동성·데이터 밀도에 적응 못 함. 채널 추가 시 데이터 분포가 바뀌어도 자동 재조정.
- `event_type` 같은 스키마 진화가 1-step 마이그레이션 가능해짐.

## v1.4.0 — 2026-04-27 (리팩토링 + 채널 확대 ergonomics)

### Refactoring
- **`llm_client.py` 신설** — OpenAI 호출 + PRICING + cost 계산 단일 모듈. theme_normalizer · methodology_synth · comparative_synth가 사용. yt_extract_v2는 안정성 위해 유지.
- **`pipeline.sh` 채널 단일 소스화** — 기존 `CHANNELS=( ... )` 하드코딩 제거 → `config.py CHANNELS`에서 동적 생성. 신규 채널 추가 시 한 곳(config.py)만 수정.
- **`config.py LENS_PRESETS`** — lens별 stock_weight·max_videos_per_run 기본값 정의. 채널 dict에서 lens만 지정하면 자동 적용 (override 가능).

### Added
- **`comparative_synth.py`** — 4채널 cross-comparison LLM 자동 합성. signals %, 추론 스타일, 단골 테마 겹침, lens별 사각지대까지 한 번에 비교. `methodologies/comparative_overview.md` AUTO 블록 갱신. 7일 게이트, ~$0.001/회.
- **`add_channel.py`** — 신규 채널 추가 CLI 헬퍼. 입력 검증·중복 체크·디렉터리 생성·snippet 출력·`--apply`로 config.py 자동 삽입.
- **pipeline.sh stage 4c 확장** — methodology_synth 후 comparative_synth 자동 실행.

### Changed
- **`wiki_ingest.py` canonical-aware** — youtuber 페이지 "Top 10 테마" 가 raw verbose name이 아니라 `theme_dictionary.json`의 canonical tag로 집계. 사전 부재 시 raw fallback.
- **`theme_normalizer.py` / `methodology_synth.py`** — 자체 OpenAI 호출 코드 제거, llm_client로 위임.

### Why
- v1.3 리뷰에서 발견된 약점: 단일 소스 지배·comparative_overview stale·duplication of LLM call code·channel addition friction. v1.4가 인프라 정합성과 채널 확대 시 1-step 추가를 가능하게 함.

## v1.3.0 — 2026-04-27 (theme×stock 매트릭스 + 개별 종목 채널 준비)

### Added
- **`theme_to_stock.py`** — canonical theme × ticker 매트릭스 생성. 채널별 `stock_weight`로 가중 점수 산출.
  - bottom-up 채널(supergaemi=1.2)이 top-down 채널(86bunga=0.6)보다 종목 attribution에 강하게 반영
  - 출력: `data/reference/theme_to_stock_matrix.json`
- **`theme_pages_gen.py` 확장** — 각 테마 페이지에 "Top 10 관련 종목" 섹션 자동 삽입 (score · 언급수 · 채널 · 최초/최근).
- **pipeline stage 4b 확장** — theme_to_stock → theme_pages_gen 순으로 실행.
- **`config.CHANNELS`에 `lens` + `stock_weight`** 메타 추가:
  - top-down: han_gyunsoo (0.8), seo_jaehyung (0.7)
  - macro: 86bunga (0.6)
  - bottom-up: supergaemi (1.2)

### Schema (v1.2.1 — 호환 유지)
- **`themes[].event_type`** 추가 (enum 12개): 실적발표 · 신제품_출시 · M&A_지분 · 규제_허가 · 수주_계약 · 배당_자사주 · 지배구조_변경 · 신사업_진출 · 구조조정 · 기관_수급 · 미해당 · 기타
- 기존 추출 파일은 이 필드 없음 — 코드는 `.get("event_type", "미해당")` 처리. 강제 재추출 없음 (`--reextract-all` 옵션은 v1.4에서 제공 예정).

### Hotfix (v1.2.0)
- **theme_normalizer LLM 태깅** — 기존 verbose 테마명(평균 30-80자)으로는 fuzzy 클러스터링이 거의 불가능 (4,707 unique 중 multi-mention 0개). gpt-5.4-nano로 1-3단어 canonical 태그 추출 후 클러스터링. 캐시(`data/reference/theme_tags_cache.json`)로 증분만 LLM 호출. 일회성 ~$0.50.

## v1.2.0 — 2026-04-27 (테마 자동 합성 + 모니터링 대시보드)

### Added
- **`theme_normalizer.py`** — 추출된 raw theme 문자열을 RapidFuzz token_set_ratio≥85로 클러스터링해 canonical 사전(`data/reference/theme_dictionary.json`) 구축. 증분 갱신 + `--rebuild` 지원.
- **`theme_pages_gen.py`** — canonical theme별 `themes/{slug}.md` 자동 생성/갱신. 라이프사이클 룰베이스 자동 분류 (Emerging / Confirming / Mature / Fading). AUTO 블록만 갱신해 수동 작성 부분 보존.
- **`theme_dashboard.py`** — 룰베이스 시그널 검출:
  - 신규(Emerging): 첫 언급 ≤ 7일 전
  - 가속(Accelerating): 7일 빈도 / 이전 30일 ≥ 3.0
  - 소멸(Fading): 마지막 언급 ≥ 45일 + 누적 ≥ 3
  - 콘센서스(Consensus): 14일 내 ≥ 2채널 동시 언급
  - 출력: `themes/_dashboard.md` + `index.md` 의 WEEKLY_PULSE 섹션
- **`methodology_synth.py`** — 채널별 추출 데이터를 gpt-5.4-nano에 전달해 메소돌로지 패턴 5–7 bullet 자동 합성. `methodologies/{channel}_pattern.md` 의 AUTO 블록만 갱신, 7일 게이트로 비용 통제 (`--force` 로 즉시 재합성).
- **pipeline.sh stages 4b / 4c / 5b** 신설 + `--skip-themes` `--skip-methodology` `--skip-dashboard` `--force-methodology` 플래그.

### Changed
- `pipeline.sh` 버전 1.1.0 → 1.2.0
- SPECIFICATIONS 데이터 흐름·출력물·기술 스택 갱신

## v1.1.0 — 2026-04-27 (프로젝트 리네이밍 + 문서 정합성)

### Changed
- 프로젝트 이름 `world_monitor` → `theme_radar` 일괄 치환 (디렉터리 명과 일치)
- launchd label `com.world_monitor.daily` → `com.theme_radar.daily`
- 모든 문서·스크립트의 경로/라벨/grep 표현식 갱신
- `pipeline.sh` 의 `PIPELINE_VERSION="1.1.0"` 과 SPECIFICATIONS 버전 동기화

## v1.0.0 — 2026-04-27 (자동화 시스템 완성)

### Added
- **자동 파이프라인** (`scripts/pipeline.sh`) — fetch → extract → catalysts → reports → wiki ingest
- **launchd 스케줄러** — 매일 06:00 자동 실행 (`scheduler/com.theme_radar.daily.plist`)
- **install/uninstall 스크립트** (`scheduler/install.sh`, `uninstall.sh`)
- **상태 점검 스크립트** (`scripts/status.sh`)
- **Wiki ingest** (`scripts/wiki_ingest.py`) — theme_radar Obsidian Vault 자동 갱신
- **3-file 표준 문서** (SPECIFICATIONS / OPERATIONS / CHANGELOG)
- **.env.example** — 환경변수 샘플

### Infrastructure
- 4개 채널 추적 (한균수, 86번가, 서재형, 슈퍼개미)
- Webshare rotating residential proxy ($3.50/월)
- gpt-5.4-nano 추출 ($0.002/영상)

## v0.9 — 2026-04-27 (Wiki + Catalysts 통합)

### Added
- **theme_radar Obsidian Vault** (iCloud sync) — Karpathy LLM Wiki 패턴
  - 12 카테고리 폴더 + 10 핵심 페이지
  - 4-Lens 통합 프레임워크 (Pre-emergence/Confirmation/Tactical/Sector)
  - 8-Signal 체크리스트
  - 라이프사이클 5단계 + 환경별 lens 가중치
- **youtube_to_catalysts.py** — 추출 결과 → catalysts.yaml 자동 변환
- **catalysts.yaml 머지** — 8개 신규 catalysts 추가 (`source: youtube_extraction` 마킹)
- **discovery 검증** — geopolitical_investor가 Top 5 중 5개 우리 catalysts 채택

## v0.8 — 2026-04-27 (Schema v3 + 시간 정규화)

### Added
- **신호 enum v3** — 6개 카테고리 추가 (회계, 거버넌스, 밸류, 공시, 파생, 역사_비교)
  - 효과: 86번가의 "기타" 27% → 3% (분석법 정확히 잡힘)
- **시간 정규화** — 시장 환경 라벨링 (8개 regime), 분기별 비교
- **comparative methodology v3** — 한균수 vs 86번가 풀 데이터 비교

## v0.7 — 2026-04-27 (86번가 풀 추출)

### Added
- **86번가 642편 v3 추출** ($0.997, 3,435 themes)
- 86번가 진짜 메소돌로지 드러남: 거시(45%) + 정책(34%) + 공시(28%) + 회계(14%) + 역사_비교(12%) + 밸류(11%) + 거버넌스(11%)

## v0.6 — 2026-04-27 (Webshare 통합)

### Added
- **Webshare Residential Proxy** — IP 차단 우회
- 86번가 642편 다운로드 완료 (98%, IP 차단 해제 후)
- yt_fetch_channel.py에 proxy 통합 + rate limit 보호 강화

## v0.5 — 2026-04-26 (KRX whitelist + 비교 보고서)

### Added
- **build_krx_whitelist.py** — KOSPI 949 + KOSDAQ 1821 종목명 정규화
- **ticker_normalize.py** — fuzzy 매칭 (rapidfuzz)
- **yt_methodology_compare.py** — 멀티채널 비교 보고서

## v0.4 — 2026-04-26 (Schema v2 + 일괄 처리)

### Added
- **스키마 v2** — themes[]별 discovery_signals + policy_diplomatic_mentions + methodology_meta
- **uncertain 프롬프트 강화** — 100% → 0%
- 한균수 14편 + 추가 28편 일괄 처리 ($0.026)

## v0.3 — 2026-04-26 (모델 비교)

### Added
- **3-way 모델 비교**: gpt-5-nano vs gpt-5.4-nano vs gpt-4.1-nano
- **결정**: gpt-5.4-nano (한국어 도메인 지식 우월)
- reasoning_effort=none 옵션 활용 ($0.002/영상)

## v0.2 — 2026-04-26 (1차 추출)

### Added
- **yt_extract_v2.py** — gpt-5-nano 기반 구조화 JSON 추출
- 한균수 14편 추출 (1차 시험)
- 메소돌로지 보고서 자동 생성

## v0.1 — 2026-04-26 (초기 구축)

### Added
- yt_fetch.py — youtube-transcript-api 기반 자막 다운로드
- 한균수 14편 트랜스크립트 (수동 큐레이션)
- INVENTORY 보고서
