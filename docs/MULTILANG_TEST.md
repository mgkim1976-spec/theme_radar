# Multi-Language 추출 테스트 (Issue #4)

**일시**: 2026-04-28  
**대상**: Bloomberg/Real Vision 스타일 영문 트랜스크립트 (synthetic, 2.4K chars)  
**모델**: gpt-5.4-nano (기존 한국어 prompt 그대로 사용)  
**테스트 파일**: `data/youtube/_test_english/extractions_v2/20260428_BBGTEST01_gpt-5.4-nano.json`

## 결론

**한국어 prompt + 영문 transcript 조합이 그대로 동작.** 모델 bilingual 능력 + prompt 의 한국어 출력 강제가 결과를 한국어 canonical form 으로 통일시킨다.

## 검증 결과

| 필드 | 결과 | 비고 |
|---|---|---|
| `themes` | ✅ 5개 추출 | 영문 컨텐츠에서 추출되었으나 이름은 한국어로 생성 |
| `discovery_signals` | ✅ 정확 매핑 | 밸류에이션_분석, 공급망_인접산업, 펀더멘털_실적 등 |
| `event_type` enum | ✅ 정확 적용 | 수주_계약, 미해당 등 한국어 enum 그대로 |
| `tickers` | ✅ 혼용 가능 | 영문(NVIDIA, AVGO, TSMC) + 한국(SK하이닉스, 삼성전자) |
| `policy_diplomatic_mentions` | ✅ 3건 캡처 | "5월 FOMC", "사우디·UAE 소버린 AI 딜", "트럼프 중국 반도체 관세" |
| `key_catalysts` | ✅ 날짜 보존 | "5월 7일 FOMC", "NVDA 실적(5월 22일)" |
| `methodology_meta` | ✅ 정확 분류 | top-down=True, news-driven=True, chart=False |
| `uncertain` | ✅ False | 정상 분석 가능 영상으로 판정 |

## 한계 / 후속 필요 작업

1. **티커 정규화 갭**
   - 영문 컨텐츠에서 캡처된 티커가 약식 표기(NVIDIA, TSMC)로 들어옴
   - `price_fetcher.DEFAULT_FOREIGN_ALIAS` 에 영문 풀네임 → 심볼 매핑 필요
     - 현재 NVIDIA → NVDA 매핑은 있으나, "Microsoft", "Alphabet" 등 추가 필요
   - 추정: 영어 채널 1개 본격 도입 시 alias 30~50개 추가 작업 필요

2. **canonical theme 충돌**
   - 영문→한국어 번역된 테마명이 기존 한국 테마와 다른 표기로 생성됨
     - 예: "AI 인프라 강세" vs 기존 "ai_인프라"
   - `theme_normalizer.py` 의 RapidFuzz 매칭 + LLM 태깅이 이를 부분 해소
   - 영어 채널 데이터가 일정 규모(>100 영상) 누적된 후 정규화 임계값 재조정 필요

3. **methodology 비교 보고서**
   - `yt_methodology_compare.py` 와 `comparative_synth.py` 는 한국 톤·스타일 가정
   - 영어 채널 추가 시 보고서는 동작하나 인용·예시가 한국어 컨텍스트에 편향됨

## 권장 도입 순서 (추후 영어 채널 추가 시)

1. `config/channels.yaml` 에 채널 추가 (lens=`macro` 또는 `top-down`)
2. `yt_fetch_channel.py` 로 transcript 1개 fetch → 추출 검증
3. `price_fetcher.DEFAULT_FOREIGN_ALIAS` 에 누락된 영문 풀네임 추가
4. `theme_normalizer.py` 재실행 → 신규 canonical 통합
5. 100 영상 누적 후 `comparative_synth.py` 로 한국 채널과 비교

## 결론 (한 줄)

**현재 시스템은 영어 컨텐츠를 추가 작업 없이 처리 가능. 본격 도입은 ticker alias 보강만 추가하면 가능.**
