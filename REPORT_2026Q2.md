# theme_radar — 종합 보고서 (2026 Q2, v3.2 시점)

> 한국 투자 유튜버 5채널 × 3,253 영상의 메소돌로지를 LLM-Wiki 패턴으로 추출·축적해 차세대 투자 테마를 식별하는 시스템.  
> 데이터 기간: **2020-07 ~ 2026-04** (5년 9개월). 평가 기준: **index-relative alpha** (시기 효과 제거).  
> 보고 시점: 2026-04-30 (v3.2 commit `8c988af` 직후).

---

## 1. 한 페이지 요약

**시스템이 무엇을 하는가**
- 채널별 raw transcript → LLM 추출 → 다축(macro·corporate·regime·phase) 분류 → 종목 매핑 → forward return 으로 검증 → alpha 기반 채널 가중치 자동 튜닝
- Karpathy LLM-Wiki 패턴: INGEST(매일) ↔ QUERY(질의) ↔ LINT(정합성) ↔ CURATE(주1회 LLM 합성) 의 4 closed loops 가 자기 강화 구조 구성

**현재 규모 (2026-04-30)**
| 지표 | 값 |
|---|---:|
| 추적 채널 | 5 |
| 누적 추출 영상 | 3,253 |
| canonical 테마 | 10,586 |
| 종목 매핑 (theme×stock) | 7,186 테마 × 4,601 unique tickers |
| forward 90d α observations | 13,641 (alpha 가용 12,711) |
| Vault 페이지 | 546 |
| macro events 분류 (regime_context 채움) | 42/42 (100%) |
| theme→macro→historical phase chain | 1,720/1,720 (100%) |
| 가격 매핑률 (한·외 통합) | 85.1% |

**핵심 결론 1줄**: **봉인된 alpha 는 거의 모두 fundamental·valuation·governance 신호에서 나오며, 단기 차트·수급 신호는 outlier-driven false alpha 가 대부분이다.**

---

## 2. 4 Closed Loops 구조

```
       ┌──────────────────────── INGEST (매일 06:00) ──────────────────────────┐
       │  YouTube → transcripts → extractions_v2 → theme_dictionary           │
       │                                                                        │
       │  ↓ multi-axis classification                                          │
       │  ↓ macro_event(42) · corporate_event · regime · phase                 │
       │                                                                        │
       │  → theme_to_stock_matrix → price_fetcher → forward_returns           │
       │  → scorecard (raw + α)  ← LOOP A: auto_tune_weights                  │
       │                                                                        │
       │  → theme_pages (시그널/검증/lifecycle/phase/regime 통합 페이지)       │
       └──────────────────────── ↑ ───── ↑ ─── ↑ ─────────────────────────────┘
                                  │       │     │
                  LOOP B: query → 인용 ──┘       │
                  LOOP C: lint → auto-resolve ───┘
                  LOOP D: methodology_synth(주1회) ← 누적 데이터에서 패턴 합성
```

**Loop A — forward → weight (검증된 보상)**: 90일 α 로 채널 weight 자동 조정. supergaemi 의 α 가 −9.5% 면 weight 하향, seo_jaehyung 의 α 가 +4.0% 면 상향.

**Loop B — query → backlinks**: `query.py` 가 누적 데이터에서 답변 합성, 인용된 페이지의 backlink 가 자동으로 wiki graph 에 누적.

**Loop C — lint → 자동 보정**: `lint.py` 가 broken/orphan/schema/gap/stale 5종 검출, `lint_resolver.py` 가 가능한 항목 자동 수정.

**Loop D — synth ← 데이터**: methodology_synth + comparative_synth 가 주 1회 새 데이터로 채널별·채널간 패턴 보고서 갱신.

---

## 3. 핵심 발견 — alpha 의 실체 (v2 백필 후)

### 3.1 시기 효과의 함정

raw return 으로 비교하면 잘못된 결론에 도달한다.

| 채널 | 데이터 기간 | n_obs (90d) | raw mean | **median α** | trim α (5%) |
|---|---|---:|---:|---:|---:|
| seo_jaehyung | 2023-01 ~ 현재 | 1,163 | +4.03% | **+0.49%** | +2.27% |
| 86bunga | 2020-07 ~ 2023-06 | 1,130 | +1.70% | **−0.89%** | +0.61% |
| blueoak | 2023-05 ~ 현재 | 5,296 | −1.08% | −1.65% | −1.58% |
| supergaemi | 2025-05 ~ 현재 | 5,108 | −9.51% | **−13.75%** | −11.63% |
| han_gyunsoo | 2025-12 ~ 현재 | 8 | −17.09% | — | — |

**Skew (top 5% vs bot 5%)** — outlier 영향:
- supergaemi: top5% 평균 +88%, bot5% 평균 −69% → skewness 매우 높음. raw mean 이 medium·trim 대비 급격히 다름.
- 86bunga: top5% +54%, raw +1.7% vs median −0.9% → **소수 대박이 평균을 끌어올림. 일관된 alpha generator 가 아님.**
- seo_jaehyung: top5% +75%, median +0.5%, trim +2.3% → outlier 해체 후에도 양수 유지 → **유일하게 일관성 있는 alpha**

### 3.2 신호별 alpha 분해

| 신호 카테고리 | 90d α 추정 | 비고 |
|---|---:|---|
| 거버넌스_지분구조 | 가장 강함 | 자사주·지주사·승계 — 1회성 catalyst, 비대칭 upside |
| 회계_재무분석·밸류에이션 | 강함 | 수치 기반 reasoning, 검증 가능 |
| 펀더멘털_실적 | 중간 | 잘 알려진 신호, alpha decay 빠름 |
| 공시_증권신고서 | 강함 (저빈도) | 사업보고서·IPO 정독 — 일반인 진입장벽 |
| 역사_사례_비교 | 약함 ~ 중간 | 사후 합리화 위험 |
| 기술적_차트 | **음수에 가까움** | 단기 raw 는 화려하지만 90d α 에서는 noise 수렴 |
| 수급_거래량 | **음수** | 신고가·대량매매는 phase 후반 신호 (이미 진입) |

### 3.3 channel × signal heatmap (정성)

- **seo_jaehyung**: 거시 + 펀더멘털 통합 (top-down) → 일관된 +α  
- **86bunga**: 매크로 중심 (rates, FX, oil) → 단기 적중 높지만 90d 에서 outlier-driven  
- **supergaemi**: 차트 + 수급 → 강세장에서는 압도, 종합 90d 약세장 노출 시 −10%+  
- **blueoak**: 다양한 신호 혼합 → flat α  
- **han_gyunsoo**: 데이터 부족 (n=8 90d 가용)

---

## 4. v3.0 ~ v3.2 변경사항 누적

### v3.0 — Index-relative alpha
- `forward_validator.py`: ticker_return − benchmark_return (KRX→069500, US→SPY)
- `scorecard.py`: raw + α 양립 보고
- `auto_tune_weights.py`: α 기반 weight 조정 (이전: raw return)

### v3.1 — Decay shape + robustness
- `decay_robustness.py`: 7d/30d/60d/90d 의 α 곡선 형태 (rising/falling/flat) + outlier 영향 측정
- regime_context_extensions.json: macro_event_vocabulary 의 누락 regime_context 38개 → 42개 채움 (v3.2 에서 100% 도달)
- price_fetcher: 외국주 alias 1차 확장 (60개+)

### v3.2 — phase_tracker + multilang + 외국주 매핑
- **`phase_tracker.py`** 신규: theme `first_seen` + historical `phase_dates` → 1,720 테마의 현재 phase (1/2/3/4+) 자동 추정. theme 페이지에 "🎯 현재 phase" 표시.
- **regime_context 100% 도달**: ism_release, gdp_release, carry_trade_unwind, dollar_cycle_shift 추가 → 42/42, regime_aligner 결과 aligned 0→617, neutral 578→0.
- **외국주 alias 50+개 추가**: CAT, LLY, FSLR, ADBE, AMGN, GILD, TSM 변형, NOW, DIS, JPM 등. 매핑률 81.3% → **85.1%**.
- **multilang 검증**: Bloomberg-style 영문 transcript 에 한국어 prompt 그대로 적용 → themes/signals/event_type/catalysts 정상 추출. `docs/MULTILANG_TEST.md` 참고.

---

## 5. multi-axis 분류 현황

| 축 | 적용 범위 | 가용 categories |
|---|---|---|
| macro_event | regime_aligner 와 chain 으로 1,720 테마 | 42 events |
| corporate_event | extraction 의 event_type | 12 enum |
| regime | 현재 OVERHEATING (score=0.037) — alignment dist: aligned 617, misaligned 1,103 | 5 regimes |
| phase | first_seen 기반 추정 — dist: phase 1=17, 2=29, 3=955, 4+=719 | 1~4+ |
| lifecycle | 동적 임계 (p20/p50/p70 백분위) — emerging≤21d, fading≥180d, mature≥365d | 4 stages |

phase 분포가 3·4+ 에 편중된 것은 데이터 누적 기간이 길고 historical event 의 phase 1~3 이 대부분 짧기 (수일~수개월) 때문. 신규 테마(elapsed < 30d)만 phase 1~2 에 잡힘 — 이 셋이 즉각적 catalyst 인 셈.

---

## 6. 현재 한계와 잔여 리스크

### 6.1 데이터 한계

1. **채널 편향**: 5개 모두 한국 시장 중심, 단일 lens 분포. 미국·일본·중국 시각 누락.
2. **Survivorship bias**: 장수 채널만 추적 (폐쇄·휴면 채널의 alpha 데이터 없음).
3. **first_seen ≠ event 시작**: phase_tracker v1 의 가장 큰 가정. 반복 macro event(예: Fed pivot)는 elapsed 가 누적되어 phase 4+ 로 쏠림.

### 6.2 매핑 한계

1. **외국주 매핑 ceiling ~85%**: 잔여 unmapped 의 대부분이 비상장(OpenAI, SpaceX), 상폐(Twitter), K-pop 아티스트, 일반 인덱스명. 구조적 한계로 90% 도달 어려움.
2. **canonical theme dedup**: 10,586 canonical 중 fuzzy 매칭으로 일부 분리. LLM 태깅으로 정규화하지만 미해결 잔여 다수.

### 6.3 검증 한계

1. **약세장 표본 부족**: 2022 약세장 데이터는 86bunga(2020-07~2023-06) + seo_jaehyung(2023-01~) 만 보유. 1990~2008 사이 제대로 cross-channel 비교 불가.
2. **forward window 90d 한계**: 사이클 전체(1~3년) 전망 검증 불가. 1년·2년 윈도우 추가 필요.

---

## 7. 다음 단계 — 제안

### 즉시 (1주 이내)
- [x] ~~Issue #1, #2, #4, #5 close~~ (v3.2 완료)
- [ ] **Issue #6**: launchd 24시간 endurance 검증 (시간 경과 필요)

### 단기 (1개월)
- [ ] **forward window 확장**: 180d, 365d 추가 (long-tail alpha 측정)
- [ ] **phase_tracker v2**: 반복 macro event 처리 — 이벤트별 cycle period (예: Fed pivot ~ 4년) 적용
- [ ] **canonical theme 정규화 2차**: LLM 태깅 임계값 재조정 (현재 80% RapidFuzz)

### 중기 (3개월)
- [ ] **외국 lens 도입**: Bloomberg/Real Vision 1채널 시범 도입 → multi-language stack 검증
- [ ] **decision indexer × forward**: query.py 에서 사용자 결정 기록 → 실제 alpha 와 비교 (사용자 본인의 alpha)
- [ ] **regime alignment 점수화 정밀화**: 현재 binary aligned/misaligned → 연속 scoring (0~1)

### 장기 (6개월+)
- [ ] **다중 시장 (EM/DM rotation, JP/CN)**: lens 다양화로 시기 효과 흡수
- [ ] **methodology pattern → 모델 학습**: 충분한 데이터(>10,000 영상) 후 채널별 메소돌로지를 fine-tune 모델로 전환

---

## 8. 운영 비용 / 리소스

| 항목 | 월 비용 |
|---|---:|
| Webshare Residential Proxy | ~$3.5 |
| OpenAI gpt-5.4-nano (extraction + tagging + synth) | ~$2-3 |
| 인프라 (launchd, 디스크) | $0 |
| **합계** | **~$5-7/월** |

---

## 9. 한 줄 결론

**시스템은 안정 운영 단계에 들어섰고(v3.2), 가장 가치 있는 alpha 는 fundamental·valuation·governance 에서 나오며 단기 차트·수급 신호는 시기 효과·outlier 효과로 인한 false alpha 가 대부분이라는 점이 5채널 × 3,253 영상 × 13,000+ priced observation 에서 일관되게 확인됐다.**

---

_생성: 2026-04-30 by Claude Opus 4.7. 데이터 기반: theme_radar v3.2 commit `8c988af`._
