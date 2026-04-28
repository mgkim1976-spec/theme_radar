# [3] 금융 도메인에서 LLM-Wiki — `theme_radar` 사례

> 앞선 글 [1] (Karpathy, *LLM-Wiki*)과 [2] (*Claude Code의 verifiable rewards*)를 이어
> 금융 도메인이 왜 LLM-Wiki의 가장 강력한 적용처인지, 그리고 이를 실제 가동 시스템으로
> 구축한 `theme_radar` 프로젝트의 구조·성과·한계를 정리한다.

---

## 도입 — 왜 금융이 LLM-Wiki에 가장 잘 맞는가

[1]의 LLM-Wiki는 강력한 비전이지만 한 가지 본질적 약점을 가진다 — **AI가 합성한 지식이 맞는지 어떻게 아는가?** 노션/옵시디언에 LLM을 얹으면 *그럴듯한* 정리는 만들어지지만, 검증 신호가 없으면 같은 단계에 영원히 머물거나 환각으로 발산한다.

[2]에서 카파시가 짚은 핵심은 **verifiable rewards**였다. Claude Code가 코딩 에이전트로서 폭발적 성능을 낸 이유는 "테스트 통과 / 컴파일 성공 / lint 0건"이라는 0·1 신호 위에 강화학습을 쌓을 수 있었기 때문이다. 작문이나 일반 대화는 그 신호가 약해 LLM이 헛소리를 해도 잡기 어렵다.

**금융 도메인은 이 점에서 특별하다.** 모든 발화에 자연적인 verifiable reward가 따라붙는다.

| 발화 유형 | Verifiable Reward |
|---|---|
| "이 종목이 갈 것이다" | 30/60/90일 후 종가 수익률 |
| "이 테마가 부상한다" | 관련 종목·섹터의 forward return |
| "이 채널의 분석은 정확하다" | win rate · mean return |
| "이 매크로 이벤트가 도래한다" | 자산별 phase 반응 (S&P, 채권, 달러, 금) |

즉 금융 LLM-Wiki는 *knowledge accumulation*에 머물지 않고 *knowledge validation까지 자동화*가 가능한 영역이다. 단순히 지식을 누적하는 것을 넘어, 그 지식이 *돈이 되는지*를 데이터가 자체적으로 검증하는 시스템을 만들 수 있다.

이 글은 그 가능성을 실제 시스템으로 구축한 `theme_radar` 프로젝트를 사례로 다룬다.

---

## theme_radar — 한 줄 요약

> **YouTube 투자 채널 4개의 메소돌로지를 자동 추출·구조화하고, 가격 데이터로 검증해 자기 학습하는 LLM-Wiki**

- **입력**: 4개 채널 (한균수·86번가·서재형·슈퍼개미) — 970개 영상 자막
- **처리**: gpt-5.4-nano로 영상별 21-카테고리 신호 추출, 채널·테마·종목·이벤트 자동 분류
- **출력**: Obsidian Vault에 ~1,100개 마크다운 페이지로 구조화
- **검증**: 매일 가격 데이터 갱신 → 채널 가중치·메소돌로지 합성을 자동 재조정
- **운영**: macOS launchd가 매일 06:00 자동 실행, 사용자 개입 0
- **비용**: 누적 LLM ~$2.3 / 월 운영 ~$5-7 (proxy + 추출)

---

## 1. 카파시 LLM-Wiki의 4가지 원칙과 매핑

| Karpathy 원칙 | theme_radar 구현 |
|---|---|
| **원시 데이터 기반** — 폴더에 던지면 AI가 알아서 | YouTube 자막을 채널별 폴더에 자동 fetch (`yt_fetch_channel.py`, Webshare proxy로 IP 차단 우회) |
| **AI 기반 정리** — 마크다운 + 링크 자동 구조화 | LLM이 영상마다 (테마, 신호, 종목, 입장, conviction)을 21-카테고리 enum으로 추출. 매일 545개 theme 페이지 + 4개 youtuber + 6개 methodology 자동 페이지화 |
| **지식의 복리화** — 새 정보가 기존과 비교·연동 | canonical theme 사전(3,843개)이 새 영상마다 *증분* 갱신. LLM-tagging 캐시(theme_tags_cache.json)로 신규만 호출. 5,073 verbose → 3,843 canonical 압축 |
| **질문도 자산** — 대화 결과가 위키에 편입 | `decisions/` 폴더 — query 답변이 출처 인용·메타·비용 포함된 영구 페이지로 보존. 인용된 source 페이지에 자동 backlink |

매핑 자체보다 중요한 건 **이 매핑이 자동으로 매일 실행된다는 점**이다. 사용자가 채널 리스트만 주면 (또는 신규 사용자가 `init_project.py` 5분 부트스트랩만 해도) launchd가 매일 06:00에 위 4가지를 모두 실행한다.

---

## 2. 핵심 차별화 — 4개 Closed Loop ("knowledge compounding"의 구체적 정의)

카파시가 말한 "복리화"는 추상적이다. theme_radar에서는 4개의 명시적 피드백 루프로 구체화된다.

### Loop A · 가격 데이터 → 채널 가중치 (auto)

```
forward_validator → scorecard → auto_tune_weights → channel_weights.json
                                                          ↓
                                                  theme_to_stock 자동 사용
```

실제 30/60/90일 수익률을 측정해 채널별 stock_weight를 자동 재조정한다. 어떤 채널이 진짜 alpha를 만드는지 *시간이 갈수록 더 정확하게* 데이터가 말해준다.

**실측 결과 (3,306 priced observations)**:

| 채널 | 90d mean | 90d win | 자동 가중치 |
|---|---:|---:|---:|
| seo_jaehyung | +37.5% | 85% | **1.55** |
| 86bunga | +2.8% | 50% | 0.70 |
| han_gyunsoo | +2.4% (30d) | 48% | 0.70 |
| supergaemi | n부족 | — | 1.20 (default) |

이 가중치가 매주 자동 갱신되며 theme×stock 매트릭스에 즉시 반영된다.

### Loop B · Query 결과 → wiki backlinks (auto)

사용자가 vault에 질문하면 (`query.py`) → 답변이 `decisions/`에 저장되고 → 인용된 source 페이지에 자동 backlink가 추가된다.

```
사용자: "한균수와 86번가의 원전 view 차이?"
   ↓ (LLM router + synth, $0.0027)
decisions/2026-04-28_한균수와_86번가의_원전_view.md  (출처: 8개 페이지)
   ↓ (자동)
themes/원전, youtubers/han_gyunsoo, methodologies/86bunga_pattern, ...
   ↓ 각 페이지에 backlink 자동 추가
citation_index.json — 자주 인용되는 페이지 = high-signal 마킹
```

**즉, 질문할수록 wiki가 강해진다**. 카파시의 "질문도 자산이 된다"가 자동 인덱싱으로 실현된다.

### Loop C · Lint findings → 자동 해결 (auto)

```
lint.py → questions/{date}_{cat}_{slug}.md → lint_resolver.py → 자동 fix
```

- broken link → LLM이 의도 파악 → 슬러그 fix 또는 stub 페이지 생성
- frontmatter schema_drift → 본문에서 추론 가능한 필드 자동 보강

**실측**: 73 questions → 67 자동 해결 (10 fix + 56 stub + 1 schema), lint findings **156 → 29 (-81%)**, LLM 비용 ~$0.05.

### Loop D · methodology synth ← forward returns (auto)

LLM이 채널별 메소돌로지를 합성할 때, **forward validation 데이터를 프롬프트에 자동 주입**한다. LLM은 정확한 숫자를 인용하며 "데이터로 검증된 부분 / 데이터로 약한 부분"을 솔직히 명시한다.

서재형 채널 합성 결과 (실제 출력):

> "Forward Validation에서 신호 발화 후 성과가 7d 평균 +2.76%(win 61.4%) → 30d +11.14%(72.5%) → 60d +23.11%(76.9%) → **90d +37.49%(84.8%)**로 시간 갈수록 강하게 누적되어, '정책/거시+실적 연결된 산업 사이클 테마'가 중기 추세에서 실효가 있었음을 데이터가 뒷받침합니다."

> "다만 이 검증은 채널 전체 발화에 대한 통계라서, 위 메소돌로지 항목 중 무엇(예: `역발상_컨센서스반대` vs `밸류에이션_분석`)이 성과를 가장 크게 만든다는 부분까지는 데이터로 분해 확정하기 어렵습니다."

LLM이 단순히 *그럴듯한* 합성을 하는 게 아니라 *데이터로 ground 된* 합성을 한다. 가설과 데이터가 충돌하면 솔직히 명시한다.

### 4-Loop의 의의

이 4개 루프가 닫히면 시스템은:
- 매일 새 데이터가 들어와도 stale 하지 않고
- 사용자가 질문할수록 wiki가 강해지고
- 정합성 문제는 자체 해결되고
- 채널·메소돌로지의 신뢰도가 데이터로 동적 검증된다

이것이 카파시가 말한 **knowledge "compounding"의 구체적 정의**다. 단순한 *accumulation* (쌓이기만 하는)과는 다른 차원이다.

---

## 3. Verifiable Rewards — 금융 LLM-Wiki의 핵심 무기

[2]의 verifiable rewards 개념을 금융 wiki에 적용한 것이 Loop A·D다.

### 일반 LLM-Wiki의 한계
- 노션/옵시디언 + LLM = 그럴듯한 정리
- 그러나 *맞는지 어떻게 아는가?*
- 작문 도구로는 충분, 의사결정 도구로는 부족

### theme_radar에서의 Verifiable Reward

| LLM 산출물 | Verifiable Reward | 측정 빈도 |
|---|---|---|
| 채널별 메소돌로지 패턴 | 30/60/90일 forward return × win_rate | 주 1회 |
| theme×stock 매트릭스 점수 | 종목 실제 수익률 | 매일 |
| 카탈리스트 분류 (event_type) | event_type별 forward return | 매일 |
| 채널 가중치 (stock_weight) | scorecard 90d × win_rate | 주 1회 |
| 매크로 이벤트 분류 | regime 적합도 (예정) | 주 1회 |

**모든 LLM 합성에 정량 검증이 따라붙는다.** Claude Code가 테스트 통과로 강화학습되듯, theme_radar는 가격 데이터로 자체 캘리브레이션된다.

### 발견된 *반증된 가설* 사례

첫 forward validation에서 발견된 사례들 — LLM 합성만으로는 절대 보이지 않을 패턴:

- **한균수**는 시그니처상 "시황+종목 단기 트레이더"로 자리잡았으나 실측 win rate **48%** (50% 미만). 모멘텀 트레이더가 손해 빈도 더 높음
- **86번가의 시그니처 신호** (`공시_증권신고서`·`거버넌스_지분구조`)의 30일 forward return은 거의 random (mean +1-2%, win 50%)
- **M&A_지분 카탈리스트**는 직관과 반대로 30일 평균 **−1.3%, win 37%**. M&A 발표가 단기적으로는 호재로 작동하지 않음
- **수주_계약 카탈리스트**가 압도적: 30일 +11%, win 71% — event_type 중 1위

이런 결과는 데이터가 자기 검증할 때만 드러난다. LLM은 학습 시점의 통념을 그대로 합성할 뿐이다.

---

## 4. Cross-Project Knowledge Graph — Snapshot 패턴

LLM-Wiki는 단일 프로젝트가 아니라 **여러 프로젝트가 어휘를 공유**할 때 진가가 발휘된다. theme_radar는 이를 "snapshot 패턴"으로 해결한다.

```
investment_ontology/                      ← 별도 프로젝트
├── macro_event_vocabulary.json (42개)    ← 매크로 이벤트 어휘
└── corporate_event_vocabulary.json (79개) ← 기업 이벤트 어휘
        ↓ vendoring (sync_vocabularies.py)
theme_radar/data/reference/vocabularies/
├── macro_event_vocabulary.snapshot.json   ← 복사본 + sha256 + provenance
└── corporate_event_vocabulary.snapshot.json
        ↓ classifier (RapidFuzz keyword + LLM fallback)
theme_radar의 canonical theme 3,843개 → 매크로 743 + 기업 1,193로 분류
```

각 vocabulary entry는 단순 enum이 아니다 — 이벤트마다 (severity, direction, impact_pct, keywords_ko, causal_chain, base_rate, regime_context) 메타데이터가 같이 들어온다. theme_radar는 이를 그대로 상속해 페이지에 노출한다:

```markdown
## Event Classification (multi-axis)
- 🌐 Macro: fed_pivot · conf=high (severity=CRITICAL, dir=mixed)
- 🏢 Corporate: earnings_beat · conf=medium (severity=HIGH, dir=positive)
```

**이 패턴의 의의**:
- theme_radar는 vocabulary를 **재사용** (자체 발명 안 함)
- 동시에 **런타임 의존성 0** (snapshot이라 upstream 사라져도 정상 동작)
- 두 프로젝트가 같은 이벤트 어휘를 공유 → 미래에 통합 분석 가능
- 어휘 갱신은 분기 1회 수동 sync — 어휘는 자주 안 변하므로 충분

이는 카파시 LLM-Wiki의 자연스러운 확장이다 — *집단 지식 그래프*. 각 프로젝트가 작은 wiki를 운영하되, 어휘/메타데이터 layer는 공유한다.

---

## 5. 결과·한계·다음 단계

### 정량 결과 (v2.4 시점, 2026-04-28)

```
페이지:               1,099개 (theme 545 / methodology 6 / youtuber 4 /
                              catalyst 9 / decision 1+ / question 67 /
                              schema·template·playbook 등)
canonical theme:      3,843 (5,073 verbose에서 1.32x 압축)
multi-axis 분류:      macro 743 + corporate 1,193 (cross-axis 검증 완료)
forward observations: 3,306 priced (528 unique tickers)
forward validation:   외국주 매핑률 80.6%, KR 100%
LLM 누적 비용:        ~$2.3 (재추출·태깅·합성 합)
월 운영비:            $5-7 (Webshare proxy + 추출 LLM)
loop closure:         4/4 (A·B·C·D 모두 자동)
```

### 주요 한계

1. **시간 분포 왜곡** — 86번가 데이터(2020-2023)와 다른 채널(2024-2026)의 시장 환경 차이. 직접 채널 비교 곤란
2. **단일 소스 지배** — AI 반도체 종목 점수의 95%가 seo_jaehyung에서 옴 (다양성 부족)
3. **외국주 매핑 80.6%** — 영어/중문 표기 변형 일부 누락
4. **decisions 활용도 낮음** — Loop B는 가동 가능하지만 사용자가 질문을 자주 던지지 않으면 의미 반감
5. **regime/phase 미통합** — 현재 시장 환경(EXPANSION/CONTRACTION) 자동 판정과 이벤트 phase tracking은 다음 iteration

### 다음 단계 (검토 중)
- **regime conditioning** — investment_ontology의 regime_detector 출력을 snapshot → 각 테마의 regime 적합도 자동 판정
- **phase tracking** — macro_events_driven_investments의 6-phase 모델 통합
- **다국어** — 현재 한국어 first, 영어 채널 추가 가능성 (Bloomberg, Real Vision 등)
- **alerting** — 신규 emerging 테마 + 매크로 이벤트 임박 시 푸시 (현재는 dashboard 갱신만)

### Portability — 다른 사용자가 자기 정보 소스로 가동

v2.3에서 yaml 외부화 + `init_project.py` 부트스트랩 도구가 들어갔다. 채널 리스트 텍스트 파일만 있으면:

```bash
# 1. my_channels.txt 작성
#    UCadSWH...  channel_subdir   lens     채널명

# 2. 부트스트랩
python3 scripts/init_project.py \
    --channels=my_channels.txt \
    --vault=/path/to/your/obsidian/vault \
    --region=KR

# 3. 실행
bash scripts/pipeline.sh
```

5분 만에 자기 채널·자기 시장으로 같은 시스템 가동. 외부 통합 (geopolitical_investor·investment_ontology) 은 모두 옵션 (`integrations.*.enabled: false`로 끌 수 있음). 자세한 내용은 `QUICKSTART.md`.

---

## 마치며 — 무엇이 진짜 LLM-Wiki를 가능하게 했나

`theme_radar`가 카파시의 비전을 실현할 수 있었던 5가지 이유:

1. **금융 도메인의 verifiable rewards** — 모든 LLM 합성에 가격 데이터로 검증 가능. [2]의 Claude Code 성공 원리와 동일한 메커니즘.
2. **하이브리드 LLM/룰 사용** — LLM은 합성·분류 fallback에만 (캐시·배치 활용). 룰베이스는 무료 작업 (정규화·라이프사이클·dashboard 시그널·매트릭스). 누적 LLM 비용 $2.3에 비용 통제.
3. **4-Loop closure** — 일반 LLM-Wiki는 INGEST만 자동. theme_radar는 4 방향 모두 closed loop. 사용자 개입 0으로 매일 학습.
4. **Snapshot 패턴** — cross-project vocabulary 재사용하되 런타임 의존성 0. 어휘는 공유하지만 wiki는 각자 운영.
5. **idempotent + portable** — 매일 재실행 안전 (deletion-based migration). 다른 사용자가 5분 부트스트랩 가능.

카파시 LLM-Wiki의 본질은 ***AI가 적극적으로 유지하는 복리 자산***이다. 일반 도메인은 "복리"의 단위(어떤 신호로 자산이 늘어나는지)가 모호하다. **금융 도메인에서는 그 단위가 가격 수익률로 명확하다** — 그래서 LLM-Wiki가 가장 빠르게, 가장 검증 가능하게 작동할 수 있는 도메인이다.

> *기록은 누적될 수 있지만, 학습은 검증 없이 일어나지 않는다.*

theme_radar는 그 둘 사이의 다리를 4개의 자동 루프로 지었다.

---

## 부록 — 시스템 구성 한눈에

```
theme_radar/
├── config/                     ← 사용자 설정 (yaml, portable)
│   ├── channels.yaml
│   ├── project.yaml
│   └── lens_presets.yaml
├── scripts/                    ← 26개 Python 모듈 + pipeline.sh
│   ├── yt_fetch_channel.py     ← Stage 1: YouTube 자막
│   ├── yt_extract_v2.py        ← Stage 2: LLM 추출
│   ├── theme_normalizer.py     ← canonical 사전 (LLM 태깅 + fuzzy)
│   ├── theme_pages_gen.py      ← 페이지 생성
│   ├── theme_to_stock.py       ← theme×stock 매트릭스
│   ├── methodology_synth.py    ← 채널별 메소돌로지 합성 (Loop D)
│   ├── comparative_synth.py    ← 채널 간 비교 합성
│   ├── macro_event_classifier  ← multi-axis 이벤트 분류
│   ├── lint.py + lint_resolver ← 정합성 (Loop C)
│   ├── query.py + decision_indexer ← Query · backlink (Loop B)
│   ├── forward_validator.py    ← 가격 검증
│   ├── auto_tune_weights.py    ← 가중치 자동 (Loop A)
│   └── ...
├── data/
│   ├── youtube/<channel>/transcripts·extractions_v2/
│   ├── prices/                 ← FDR 캐시 (gitignore)
│   └── reference/
│       ├── compiled/           ← 매일 재생성 artifact (gitignore)
│       ├── cache/              ← LLM 캐시 (영구)
│       └── vocabularies/       ← cross-project snapshot
└── (Vault — Obsidian, iCloud sync)
    ├── themes/                 ← 545 자동 페이지
    ├── methodologies/          ← 4채널 패턴 + 비교
    ├── youtubers/              ← 채널 프로파일
    ├── catalysts/              ← 자동 변환 정책 이벤트
    ├── decisions/              ← Query 결과 영구 보존
    ├── questions/              ← Lint findings (자동 해결)
    └── validation/scorecard.md ← Forward returns 종합
```

자동 실행 순서 (매일 06:00 launchd):

```
1.  Fetch        YouTube 자막
2.  Extract      LLM 추출
3.  Catalysts    catalysts.yaml 변환 (옵션)
4.  Reports      methodology_compare
4b. Themes       canonical + matrix + multi-axis 분류 + 검증
4c. Methodology  채널 + comparative LLM 합성 (Loop D 자동)
5.  Wiki         페이지 갱신
5b. Dashboard    emerging/accelerating/fading
5c. Lint         정합성 + decision_indexer (Loop B·C 자동)
6.  Validation   prices·forward returns·scorecard·auto_tune (Loop A 자동)
```

---

**참고**:
- 프로젝트: `~/MGPrj/theme_radar/`
- 코드: 26개 Python 모듈 + 1 bash pipeline (~3,500 라인)
- 문서: `SPECIFICATIONS.md` / `OPERATIONS.md` / `CHANGELOG.md` / `QUICKSTART.md`
- 버전: v2.4.0 (2026-04-28)
- 누적 LLM 비용: ~$2.3 (재추출 1.93 + 태깅·합성·검증 0.4)
- launchd: `com.theme_radar.daily` 매일 06:00 자동 실행
