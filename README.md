# theme_radar

> **금융 도메인 LLM-Wiki** — YouTube 투자 채널의 메소돌로지를 자동 추출·구조화하고 가격 데이터로 자기 검증하는 시스템

[Karpathy의 LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 패턴을 금융 도메인에 적용. 4개 자동 학습 루프 (forward returns → 채널 가중치 / Query → 백링크 / Lint → 자동 해결 / methodology synth ← forward returns) 가 매일 06:00 launchd로 실행.

## 무엇을 하는가

```
입력:  YouTube 투자 채널 N개의 자막
처리:  LLM이 영상마다 (테마·신호·종목·이벤트) 21-카테고리로 추출
출력:  Obsidian Vault에 1,000+ 자동 페이지 + 매일 today.md 한 페이지
검증:  매일 가격 데이터 갱신 → 채널 가중치·메소돌로지 자동 재조정
```

매일 아침 `vault/today.md` 한 페이지만 열면 끝.

## 4개 Closed Loop (knowledge compounding)

| Loop | 방향 |
|---|---|
| **A** | forward returns → channel `stock_weight` 자동 갱신 |
| **B** | query 답변 → 인용 페이지에 자동 backlink + citation index |
| **C** | lint findings → questions/ → LLM이 자동 해결 |
| **D** | forward returns → methodology synth 프롬프트에 데이터 주입 |

## Quickstart (5분)

```bash
# 1. 채널 리스트 작성 (config/channels.example.txt 참고)
cp config/channels.example.txt my_channels.txt
# my_channels.txt 편집 (UC...ID  subdir  lens  채널명)

# 2. 부트스트랩
python3 scripts/init_project.py \
    --channels=my_channels.txt \
    --vault=./vault \
    --region=KR

# 3. .env 생성
cp .env.example .env
# OPENAI_API_KEY, WEBSHARE_PROXY_URL 입력

# 4. 첫 실행
bash scripts/pipeline.sh

# 5. 자동화 (매일 06:00, macOS launchd)
bash scheduler/install.sh
```

자세한 가이드: [QUICKSTART.md](./QUICKSTART.md)

## 주요 구성

```
theme_radar/
├── config/                     사용자 설정 (yaml, portable)
│   ├── channels.example.yaml
│   ├── project.example.yaml
│   └── lens_presets.yaml
├── scripts/                    29 Python 모듈 + pipeline.sh
│   ├── yt_fetch_channel.py     YouTube 자막 다운로드
│   ├── yt_extract_v2.py        LLM 추출 (gpt-5.4-nano)
│   ├── theme_normalizer.py     canonical 사전 (LLM tagging + fuzzy 클러스터)
│   ├── theme_to_stock.py       theme×stock 매트릭스 (자동 가중치)
│   ├── methodology_synth.py    채널별 메소돌로지 LLM 합성
│   ├── comparative_synth.py    채널 간 비교 합성
│   ├── macro_event_classifier  multi-axis 이벤트 분류
│   ├── lint.py + lint_resolver Vault 정합성 자동 (Loop C)
│   ├── query.py + decision_indexer  Query · backlink (Loop B)
│   ├── forward_validator.py    실 가격 검증
│   ├── auto_tune_weights.py    가중치 자동 (Loop A)
│   ├── daily_digest.py         "오늘의 한 페이지" today.md
│   └── ...
├── data/
│   ├── youtube/<channel>/      자막·추출 (gitignore)
│   ├── prices/                 FDR 캐시 (gitignore)
│   └── reference/
│       ├── compiled/           매일 재생성 artifact (gitignore)
│       ├── cache/              LLM 캐시 (영구 가치)
│       └── vocabularies/       cross-project snapshot
├── scheduler/                  macOS launchd
└── (Vault, 사용자별 외부)
```

## Verifiable Rewards — 금융 도메인의 핵심

[Karpathy: Claude Code의 verifiable rewards](https://x.com/karpathy/status/2042334451611693415) 가 코딩에서 통한 이유 (테스트 통과 = 0/1 신호) 가 금융에서도 자연스럽게 작동:

| LLM 산출물 | Verifiable Reward |
|---|---|
| 채널 메소돌로지 | 30/60/90일 forward return × win_rate |
| theme×stock 점수 | 종목 실제 수익률 |
| event_type 분류 | event_type별 forward return |
| 채널 가중치 | scorecard 90d × win_rate |

**모든 LLM 합성에 정량 검증.** 일반 LLM-Wiki는 *그럴듯한* 정리에 머무르지만, 금융 도메인은 *맞는지* 데이터가 자체 답변.

## 비용

| 항목 | 비용 |
|---|---:|
| Webshare Residential Proxy | $3.50/월 |
| OpenAI 추출 (gpt-5.4-nano) | $1-3/월 |
| Theme tagging·합성·검증 LLM | ~$0.05/월 |
| FinanceDataReader 가격 | $0 |
| **합계** | **~$5-7/월** |

누적 LLM 비용 ($2.3) 의 대부분은 일회성 (재추출·태깅·classification).

## 외부 의존성

- **필수**: OpenAI API · FinanceDataReader · Webshare proxy
- **옵션** (모두 `config/project.yaml` 의 `integrations.*.enabled` 로 끄기 가능):
  - `geopolitical_investor` 프로젝트 (catalysts.yaml 단방향 작성)
  - `investment_ontology` 프로젝트 (macro/corporate event vocabulary, regime data)
  - `macro_events_driven_investments` 프로젝트 (phase KB)

옵션 통합이 없으면 해당 stage 자동 스킵 — 정상 작동.

## 더 읽을 것

- [QUICKSTART.md](./QUICKSTART.md) — 신규 사용자 가이드
- [SPECIFICATIONS.md](./SPECIFICATIONS.md) — 시스템 설계
- [OPERATIONS.md](./OPERATIONS.md) — 운영 가이드
- [CHANGELOG.md](./CHANGELOG.md) — 버전 이력 (v0.1 → v2.6)
- [LLM_Wiki_금융도메인.md](./LLM_Wiki_금융도메인.md) — Karpathy LLM-Wiki를 금융 도메인에 적용한 사례 분석

## License

MIT (또는 사용자 결정)

---

이 시스템은 본래 [@mgkim1976-spec](https://github.com/mgkim1976-spec) 의 개인 투자 분석 프로젝트로 출발. v2.3 부터 portability 확보로 다른 사용자도 자기 채널·시장에 적용 가능.
