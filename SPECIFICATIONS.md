# theme_radar — Specifications

> YouTube 투자 유튜버들의 메소돌로지를 LLM으로 추출·축적하여 차세대 투자 테마를 식별하는 시스템.

## 목적

1. **메소돌로지 학습**: 한국 투자 유튜버들이 어떤 신호를 어떻게 조합해 테마를 발굴하는지 데이터화
2. **테마 발굴 자동화**: 추출된 메소돌로지를 활용하여 다음 테마를 미리 식별
3. **카탈리스트 캘린더**: 정책·외교 이벤트 사전 감지 → catalysts.yaml 자동 등록
4. **지식 자산 축적**: theme_radar Obsidian Vault (Karpathy LLM Wiki 패턴)

## 추적 채널 (4개, 단일 진실 원천: `config/channels.yaml`)

| ID | Channel ID | Lens | stock_weight | 데이터 기간 |
|---|---|---|---:|---|
| `han_gyunsoo` | UCadSWH0pDXxEatvLHEHCWlg | top-down | 0.8 | 2025-12 ~ 현재 |
| `86bunga` | UCR6Z2_Zg3M9lpot90vpZGdw | macro | 0.6 | 2020-07 ~ 2023-06 |
| `seo_jaehyung` | UCtmKBFeri9hx9DOaVSSvvvw | top-down | 0.7 | 2023-01 ~ 현재 |
| `supergaemi` | UCowHl0BGalL433P6bCBgeKA | bottom-up | 1.2 | 2017-05 ~ 현재 |

**Lens preset** (config.LENS_PRESETS): `macro` 0.6 · `top-down` 0.8 · `sector` 0.9 · `bottom-up` 1.2 — 신규 채널은 lens만 지정하면 자동 적용됨. 추가는 `python3 scripts/add_channel.py UC... <subdir> <lens> "[채널명]" --apply`.

## 데이터 흐름

```
[YouTube] ──fetch──▶ [transcripts/] ──extract──▶ [extractions_v2/]
                                                       │
        ┌──────────────────────┬───────────────────────┴──────────────┐
        ▼                      ▼                       ▼              ▼
  [catalysts_from_     [METHODOLOGY/        [theme_dictionary.json]  [methodologies/
   youtube.yaml]        COMPARATIVE 보고서]   ↓                        {channel}_
        │                                    [themes/{slug}.md]        pattern.md]
        ▼                                    +라이프사이클              (LLM 합성)
  [geopolitical_                              ↓
   investor]                                 [themes/_dashboard.md
   catalysts.yaml                             신규/가속/소멸/콘센서스]
   (자동 발행물 강화)                            +index.md WEEKLY_PULSE
```

## 모델·기술 스택

| 영역 | 도구 | 비용 |
|---|---|---|
| 자막 다운로드 | yt-dlp + youtube-transcript-api + Webshare proxy | $3.50/월 |
| 추출 | OpenAI gpt-5.4-nano (reasoning_effort=none) | $0.002/영상 |
| 종목 정규화 | KRX FinanceDataReader + rapidfuzz | $0 |
| 카탈리스트 변환 | youtube_to_catalysts.py | $0 |
| 보고서 생성 | yt_methodology_compare.py | $0 |
| **테마 정규화 (v1.2)** | theme_normalizer.py (gpt-5.4-nano 태깅 + rapidfuzz) | ~$0.5 일회성, 증분 무시 |
| **테마 페이지 자동 (v1.2)** | theme_pages_gen.py (룰베이스 라이프사이클 + 종목 매트릭스) | $0 |
| **메소돌로지 합성 (v1.2)** | methodology_synth.py (gpt-5.4-nano, 주1회) | ~$0.8/월 |
| **테마 대시보드 (v1.2)** | theme_dashboard.py (룰베이스 검출) | $0 |
| **theme×stock 매트릭스 (v1.3)** | theme_to_stock.py (채널 가중 score) | $0 |
| **채널 비교 합성 (v1.4)** | comparative_synth.py (gpt-5.4-nano, 주1회) | ~$0.02/월 |
| **LLM 클라이언트 중앙화 (v1.4)** | llm_client.py (PRICING + cost 단일정의) | — |
| **동적 lifecycle (v1.5)** | lifecycle.py (percentile + floor/cap) | $0 |
| **스키마 마이그레이션 (v1.5)** | reextract_missing_field.py + pipeline `--reextract-missing` | 변경 시 ~$2 |
| **Lint Static (v1.6)** | lint.py (broken/orphan/schema/gap/stale) | $0 |
| **Query Workflow (v1.6)** | query.py (router + synth, decisions/ 저장) | ~$0.003/회 |
| **Macro Event 분류 (v1.7)** | macro_event_classifier.py (Stage A 키워드 + Stage B LLM) | ~$0.005 일회성 |
| **Vocabulary Snapshot (v1.7)** | sync_vocabularies.py (investment_ontology 재사용, 의존성 0) | $0 |
| **Forward Validation (v2.0)** | price_fetcher + forward_validator + scorecard | $0 (FDR free) |
| Wiki | Obsidian + iCloud sync | $0 |
| 스케줄러 | macOS launchd (매일 06:00) | $0 |

총 운영 비용: **~$5-10/월** (proxy + LLM)

## 추출 스키마 (v3 + event_type)

`themes[].event_type` (v1.3, 12개 enum): 실적발표 · 신제품_출시 · M&A_지분 · 규제_허가 · 수주_계약 · 배당_자사주 · 지배구조_변경 · 신사업_진출 · 구조조정 · 기관_수급 · 미해당 · 기타

총 21개 신호 카테고리:
- **거시**: 거시지표, 정책_규제_국내/해외, 외교_정상회담, 통상_관세, 의회_입법, 지정학_분쟁
- **자금·수급**: 기관자금흐름, 수급_거래량, 파생상품_옵션포지션
- **차트**: 기술적_차트
- **펀더멘털**: 펀더멘털_실적, 공급망_인접산업, 공시_증권신고서, 회계_재무분석, 밸류에이션_분석, 거버넌스_지분구조, 내부자_경영진_움직임
- **메타**: 역사_사례_비교, 역발상_컨센서스반대, 기타

## 출력물

| 파일 | 위치 | 갱신 빈도 |
|---|---|---|
| 트랜스크립트 | `data/youtube/<channel>/transcripts/` | 매일 fetch |
| 추출 JSON | `data/youtube/<channel>/extractions_v2/` | 매일 |
| METHODOLOGY_REPORT.md | `data/youtube/han_gyunsoo/` | 매일 |
| COMPARATIVE_METHODOLOGY.md | `data/youtube/` | 매일 |
| catalysts_from_youtube.yaml | `~/MGPrj/geopolitical_investor/data/` | 매일 |
| **theme_dictionary.json** (v1.2) | `data/reference/` | 매일 (증분) |
| **theme_tags_cache.json** (v1.2) | `data/reference/` | 증분만 LLM |
| **theme_to_stock_matrix.json** (v1.3) | `data/reference/` | 매일 |
| **themes/{slug}.md** (v1.2) | Vault, ~수십~수백 페이지 | 매일 |
| **methodologies/{channel}_pattern.md** (v1.2) | Vault | 주 1회 (LLM) |
| **themes/_dashboard.md** (v1.2) | Vault | 매일 |
| **index.md WEEKLY_PULSE** (v1.2) | Vault | 매일 |
| theme_radar Wiki (youtuber stats) | iCloud Obsidian Vault | 매일 (auto stats) |
| 파이프라인 로그 | `logs/pipeline_YYYYMMDD.log` | 매 실행 |

## 자동화 스케줄

| 시점 | 작업 | 트리거 |
|---|---|---|
| 매일 06:00 | 전체 파이프라인 (fetch → extract → catalysts → reports → wiki) | launchd |
| (수동) | 채널 추가 / 신호 enum 변경 / wiki 페이지 직접 편집 | 사용자 |

## 의존성

- Python 3.13+ (pyenv)
- 외부 패키지: openai, yt-dlp, youtube-transcript-api, finance-datareader, rapidfuzz, pyyaml
- macOS launchd
- iCloud Drive (Obsidian sync)
- (외부 서비스) OpenAI API, Webshare Residential Proxy

## 비용 분석 (월간)

| 항목 | 비용 | 비고 |
|---|---:|---|
| Webshare Rotating Residential 1GB | $3.50 | 일회성, 사용량까지 유효 |
| OpenAI gpt-5.4-nano | $1-3 | 신규 영상 일일 ~10편 가정 |
| 인프라 (launchd, 디스크) | $0 | OS 제공 |
| **합계** | **~$5-7/월** | |

## 관련 시스템

- **catalysts.yaml** (`~/MGPrj/geopolitical_investor/`) — 자동 변환 결과 머지 (사용자 검토)
- **theme_radar** (iCloud Obsidian Vault) — Karpathy LLM Wiki 패턴 적용
- **MGPrj 다른 프로젝트와는 미통합** (실험 단계)

## 버전

현재: v3.1.0 (2026-04-30)
