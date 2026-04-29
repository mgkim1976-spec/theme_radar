# Query Patterns — `decisions/` 활용 가이드

> Loop B (Query → wiki backlinks) 가 가동되려면 사용자가 query를 던져야 한다.
> 이 문서는 매일 던질 만한 query 패턴 카탈로그.
>
> **사용**: `python3 scripts/query.py "<질문>"`
> 결과는 `vault/decisions/{date}_{slug}.md` 에 영구 보존되고, 인용 페이지에 자동 backlink.
> 비용: 회당 ~$0.003

---

## 1. 단계별 (lifecycle stage 기반)

### 🆕 Emerging — 신규 등장 분석
```
"오늘 신규 emerging 중 forward 검증 강한 채널이 가장 많이 잡은 것?"
"이번 주 emerging 중 90d alpha 양수 채널과 겹치는 테마?"
"hbm_사이클 같은 신규 테마의 종목 매핑은?"
```

### 🚀 Accelerating — 가속 분석
```
"이번 주 가속 진입한 테마의 공통 신호는?"
"반도체_신고가 가속 — 어떤 채널이 먼저 잡았나?"
"가속 중인 테마 중 historical event_id와 매칭되는 것?"
```

### 🤝 Consensus — 합의 분석
```
"3채널 합의 테마 중 종목 매트릭스 점수 top?"
"채널 합의 강해지는 테마와 약해지는 테마 비교?"
"ai_반도체 합의 — 채널별 종목 attribution 차이?"
```

### 📉 Fading — 소멸 분석
```
"최근 fading 진입한 테마들의 공통점 (실패한 narrative)?"
"86bunga 시기 테마 중 다시 살아난 것 있나?"
"인플레이션 fading 후 새로 떠오른 매크로 narrative?"
```

---

## 2. Cross-channel validation (alpha 검증)

```
"한균수 win rate가 낮은 이유 — 어떤 event_type이 underperform?"
"86번가의 거버넌스 신호 vs 실 종목 alpha 비교"
"seo_jaehyung 산업 사이클 vs supergaemi 차트·수급 — 어떤 게 진짜 alpha?"
"5채널 중 약세장 (2022-2023) 시기 alpha 양수 채널은?"
"blueoak 외국인 모니터링이 alpha로 변환 안 되는 이유?"
```

---

## 3. 시간축 분석 (decay / phase)

```
"1개월 전 emerging이었던 테마들이 지금 어디로 갔나?"
"AI 인프라 테마 — 7d/30d/60d/90d alpha curve 어떻게 진화?"
"빅테크 실적 발표 후 30일 평균 결과 vs 90일?"
"86bunga 약세장 (2022) 발화 테마들의 90일 결과?"
```

---

## 4. Event Type × Channel 교차

```
"M&A_지분 카탈리스트 alpha −6.6% — 어떤 채널이 주로 잡았나?"
"수주_계약 +1.78% alpha — 채널별 적중률 비교?"
"규제_허가 카테고리 분석 — 약세장과 강세장 차이?"
"실적발표 alpha 거의 0인 이유 — 시장 선반영 또는 분석 한계?"
```

---

## 5. Theme deep dive

```
"반도체_신고가 vs ai_인프라 — 어떤 게 더 sustainable?"
"바이오 카테고리 −20% alpha — 채널별 인식 차이는?"
"스테이블코인 −35% — 5채널이 어떻게 다뤘나?"
"자사주_매입 +22.5% alpha — 어떤 종목이 driver?"
```

---

## 6. Regime conditioning

```
"OVERHEATING regime에서 가장 적합한 채널 메소돌로지?"
"86bunga의 매크로 신호 — 현재 regime에 맞나?"
"regime 전환기 (2023 회복) 시기 어떤 채널이 먼저 적응?"
```

---

## 7. Methodology synthesis

```
"5채널 메소돌로지 중 데이터로 가장 검증된 것은?"
"86번가의 약세장 alpha의 비결 — 어떤 신호 조합?"
"seo_jaehyung 산업 사이클 분석법을 다른 채널이 따라하면?"
```

---

## 8. 의사결정 보조

```
"오늘 종목 진입 추천 — alpha + win_rate 기반 top 5?"
"포트폴리오 배분 — alpha 양수 테마 가중치?"
"손절 규칙 — fading 진입 시점 기준?"
"OVERHEATING regime에서 회피해야 할 테마?"
```

---

## Tips

### 좋은 query
- 구체적 (테마·채널·기간 명시)
- 검증 가능 (forward returns 데이터로 답할 수 있는)
- 비교형 ("X vs Y")

### 피할 query
- 너무 추상적 ("시장 어떻게 됨?")
- 데이터 외 정보 필요한 것 ("내일 종목 추천")
- 단순 lookup ("ai_반도체 페이지 보여줘" — 그냥 vault에서 직접)

---

## 자동화 추천

매일 아침 today.md 열어보면서 자연스럽게 query 던지는 순서:

1. **today.md 의 NEW emerging 5개 중 1개 골라** → query: "이 테마의 channel 분포 + alpha 가능성?"
2. **새 합의 강화 테마** → query: "어떤 채널 조합인지, 종목 attribution top?"
3. **새 fading 진입 테마** → query: "왜 이게 fading 됐나, 다른 어떤 테마로 자금 이동?"

**1주일 = 21개 decision 누적** → wiki 자동 강해짐 (Loop B compounding 발동).
