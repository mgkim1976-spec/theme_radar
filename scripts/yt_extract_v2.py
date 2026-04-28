"""Schema v2: per-theme discovery signals + 정책/외교 시그널 통합.

Extract structured theme + methodology data from a YouTube transcript.
Focus on the speaker's REASONING PATH (how they arrived at each theme), not just what they said.
"""
import json
import sys
from pathlib import Path
from openai import OpenAI

# === Discovery signal categories v3 (테마별 발굴 근거) ===
SIGNAL_ENUM = [
    # 거시·정책
    "거시지표",            # 금리·환율·유가·국채금리·인플레·CPI·고용
    "정책_규제_국내",      # 한국 정부 정책·법안·보조금·규제
    "정책_규제_해외",      # 미·중·EU 정책·규제 (IRA, CHIPS, 한한령 등)
    "외교_정상회담",       # 정상회담·장관회담 사전·결과
    "통상_관세",           # 관세·무역협정·수출통제·반덤핑
    "의회_입법",           # 국회·美의회 법안·청문회·결의안
    "지정학_분쟁",         # 전쟁·분쟁·군사 충돌·제재
    # 자금·수급
    "기관자금흐름",        # 외인·기관 매수, ETF 자금, 13F, 5% 공시
    "수급_거래량",         # 거래량 폭증·신고가·대량매매
    "파생상품_옵션포지션", # 옵션 OI, 콜·풋 비율, CDS, 선물 미결제, 헤지 포지션 [신규 v3]
    # 차트·기술적
    "기술적_차트",         # 차트 패턴·이평선·돌파·신고가·VIX
    # 기업·재무·밸류
    "펀더멘털_실적",       # 실적·가이던스·마진·매출
    "공급망_인접산업",     # 상류·하류 기업 상황 (HBM→메모리 등)
    "공시_증권신고서",     # 사업보고서·증권신고서·IPO 공시 정독·분기보고서 [신규 v3]
    "회계_재무분석",       # 회계 처리 변화·매출 인식 패턴·재무비율·DCF 모델 [신규 v3]
    "밸류에이션_분석",     # PER/PBR/EV/EBITDA·NAV·주식분할 효과 [신규 v3]
    "거버넌스_지분구조",   # 자사주매입·지주사 전환·삼성생명법·계열사 지배 [신규 v3]
    "내부자_경영진_움직임",# 임원 매수/매도, 합병 발표
    # 메타·기타
    "역사_사례_비교",      # 과거 사례·역사적 패턴·다른 국가 비교 [신규 v3]
    "역발상_컨센서스반대", # 컨센서스 반대 포지션
    "기타",
]

EVENT_TYPE_ENUM = [
    "실적발표",        # 분기/연간 실적·가이던스 발표
    "신제품_출시",     # 신제품·신서비스·신모델 런칭
    "M&A_지분",        # 인수합병·지분 매수/매도·5% 공시
    "규제_허가",       # 인허가·승인·규제 통과
    "수주_계약",       # 대형 수주·납품·전략적 제휴
    "배당_자사주",     # 배당·자사주매입·소각
    "지배구조_변경",   # 분할·합병·지주사 전환·승계
    "신사업_진출",     # 신규 사업 진출·인접 산업 확장
    "구조조정",        # 사업부 매각·인력 조정·재편
    "기관_수급",       # 기관·외인 대규모 매매·수급 이벤트
    "미해당",          # 종목 단위 카탈리스트 없음 (테마/매크로 위주)
    "기타",
]


POLICY_EVENT_ENUM = [
    "한미정상회담", "한중정상회담", "한일정상회담", "한미일정상회담",
    "G7", "G20", "APEC", "UN총회",
    "한미경제대화", "한미통상장관회담", "한중외교장관회담",
    "美대통령선거", "한국선거",
    "FOMC", "한은_금통위", "ECB", "BOJ",
    "美CHIPS법", "美IRA", "EU_CRMA", "K_칩스법",
    "어닝시즌", "기타",
]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["overall_market_view", "themes", "tickers_mentioned",
                 "policy_diplomatic_mentions", "key_catalysts",
                 "warnings", "methodology_meta", "uncertain"],
    "properties": {
        "overall_market_view": {
            "type": "string",
            "description": "한 문장 시장 전망 (강세/약세/중립 + 핵심 이유)"
        },
        "themes": {
            "type": "array",
            "description": "화자가 명시적으로 다룬 테마. 각 테마마다 화자가 사용한 발굴 신호를 매핑하라.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "stance", "conviction", "rationale",
                             "discovery_signals", "tickers", "time_horizon",
                             "event_type"],
                "properties": {
                    "name": {"type": "string", "description": "테마명 (예: 원전, 2차전지, K-바이오)"},
                    "stance": {"type": "string", "enum": ["bullish", "bearish", "neutral", "watch"]},
                    "conviction": {"type": "integer", "minimum": 1, "maximum": 5},
                    "rationale": {"type": "string", "description": "화자가 이 테마/입장에 도달한 추론 (1-2문장)"},
                    "discovery_signals": {
                        "type": "array",
                        "description": "이 테마 판단에 화자가 실제로 사용한 신호. 영상 전체가 아니라 이 테마에 한정. 보통 2-4개. enum 외 절대 금지.",
                        "items": {"type": "string", "enum": SIGNAL_ENUM},
                        "minItems": 1,
                    },
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "time_horizon": {
                        "type": "string",
                        "enum": ["intraday", "1주", "1개월", "3-6개월", "6-12개월", "장기", "미언급"]
                    },
                    "event_type": {
                        "type": "string",
                        "enum": EVENT_TYPE_ENUM,
                        "description": "이 테마와 결부된 종목 단위 카탈리스트 이벤트 타입 (개별 종목 분석 채널에서 주로 채워짐). 매크로/테마만 다루면 '미해당'."
                    },
                }
            }
        },
        "tickers_mentioned": {
            "type": "array",
            "description": "전체 영상에서 언급된 모든 종목 (중복 제거, 한국명 원문)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "context"],
                "properties": {
                    "name": {"type": "string"},
                    "context": {"type": "string", "enum": ["positive", "negative", "neutral", "warning"]}
                }
            }
        },
        "policy_diplomatic_mentions": {
            "type": "array",
            "description": "화자가 언급한 정책·외교·정상회담 이벤트 (예정·진행중·과거 모두). 각 이벤트마다 어떤 종목/섹터에 영향을 줄 것이라 봤는지.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["event_type", "event_label", "timing", "expected_impact_sectors", "stance"],
                "properties": {
                    "event_type": {"type": "string", "enum": POLICY_EVENT_ENUM},
                    "event_label": {"type": "string", "description": "구체 이벤트명 (예: '5월 FOMC', '6월 한미정상회담')"},
                    "timing": {"type": "string", "enum": ["과거", "진행중", "임박_1개월내", "예정_1-3개월", "예정_3개월이상", "미언급"]},
                    "expected_impact_sectors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "화자가 영향 받을 거라 본 섹터/테마"
                    },
                    "stance": {"type": "string", "enum": ["호재", "악재", "중립", "불확실"]},
                }
            }
        },
        "key_catalysts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "향후 주목 촉매 (정책·실적·지표 모두)"
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "화자가 경고한 리스크"
        },
        "methodology_meta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["primary_signals", "uses_macro_top_down", "uses_news_driven",
                         "uses_chart_technical", "mentions_foreign_flows"],
            "properties": {
                "primary_signals": {
                    "type": "array",
                    "description": "이 영상 전체에서 화자가 가장 자주 활용한 상위 3개 신호 카테고리",
                    "items": {"type": "string", "enum": SIGNAL_ENUM},
                    "maxItems": 3,
                },
                "uses_macro_top_down": {"type": "boolean", "description": "거시→섹터→종목 하향식 추론을 사용?"},
                "uses_news_driven": {"type": "boolean", "description": "최신 뉴스/이벤트를 발굴 출발점으로 사용?"},
                "uses_chart_technical": {"type": "boolean", "description": "차트·기술적 지표를 의사결정에 사용?"},
                "mentions_foreign_flows": {"type": "boolean", "description": "외인·기관 자금 흐름을 언급?"},
            }
        },
        "uncertain": {"type": "boolean"}
    }
}

PROMPT = """당신은 한국 주식 유튜브 트랜스크립트 분석가입니다.
이 분석의 핵심 목적: **화자가 어떤 추론 경로로 각 테마/종목에 도달했는지** 데이터화하는 것.
(어떤 종목을 말했는지 ≠ 왜·어떻게 그 종목에 도달했는지)

추출 규칙:

1. **themes[].discovery_signals** (가장 중요)
   각 테마마다 화자가 실제로 사용한 발굴 신호를 1-4개 선택.
   영상 전체가 아니라 "이 테마"에 한정. 모든 카테고리 다 선택 금지.

   주요 카테고리 가이드:
   - 거시지표: 금리·환율·유가·인플레·고용 데이터 분석
   - 정책_규제_국내/해외: 정부 정책·법안·규제 변화
   - 외교_정상회담: 정상·장관회담 어젠다·결과
   - 기관자금흐름: 외인·기관 매수, 5% 공시, 13F 분석
   - 수급_거래량: 거래량 폭증·신고가·대량매매
   - 파생상품_옵션포지션: 옵션 OI, 콜·풋, CDS, 헤지 포지션
   - 기술적_차트: 차트 패턴·이평선·VIX
   - 펀더멘털_실적: 실적·가이던스·마진
   - 공급망_인접산업: 상류·하류 기업 상황
   - 공시_증권신고서: 사업보고서·IPO 신고서·분기보고서 정독
   - 회계_재무분석: 회계 변경·재무비율·매출 인식 패턴
   - 밸류에이션_분석: PER/PBR/DCF/NAV·주식분할 효과
   - 거버넌스_지분구조: 자사주·지주사 전환·삼성생명법·지배구조
   - 내부자_경영진_움직임: 임원 매수/매도·합병 발표
   - 역사_사례_비교: 과거 비슷한 사례·다른 국가 비교
   - 역발상_컨센서스반대: 컨센서스 반대 포지션

   예 1: "정부가 원전 정책 발표, 두산에너빌리티 거래량 폭증" → ["정책_규제_국내", "수급_거래량"]
   예 2: "삼성물산 지배구조 개편으로 자사주 매입 유력" → ["거버넌스_지분구조", "내부자_경영진_움직임"]
   예 3: "S&P500 PER 22배는 5년 평균 대비 비싸다" → ["밸류에이션_분석"]
   예 4: "2008년 금융위기 때와 지금 신용스프레드 비슷" → ["역사_사례_비교"]
   "기타"는 정말로 위에 안 맞을 때만 사용.

2. **policy_diplomatic_mentions** (필수 캡처)
   화자가 언급한 정책·외교 이벤트는 모두 잡기:
   - "5월 FOMC", "트럼프 발언", "한미정상회담", "관세", "IRA", "CHIPS법", "한한령" 등
   - 단순 언급도 캡처 (timing: "미언급"이라도)
   - 화자가 어떤 종목/섹터에 영향 갈 거라 봤는지 expected_impact_sectors에 기록

3. **themes[].event_type** (개별 종목 카탈리스트 분류)
   각 테마에 결부된 종목 단위 이벤트 타입을 enum에서 1개 선택:
   - 실적발표: 분기/연간 실적·가이던스
   - 신제품_출시: 신제품/신서비스 런칭
   - M&A_지분: 인수합병·지분 매수/매도·5% 공시
   - 규제_허가: 인허가·승인·규제 통과
   - 수주_계약: 대형 수주·납품·제휴
   - 배당_자사주: 배당·자사주매입·소각
   - 지배구조_변경: 분할·합병·지주사·승계
   - 신사업_진출: 신규 사업·인접 산업 확장
   - 구조조정: 사업부 매각·인력 조정
   - 기관_수급: 외인·기관 대규모 매매
   - 미해당: 매크로/테마 위주, 종목 카탈리스트 없음
   - 기타

4. **methodology_meta** (집계용)
   영상 전체의 추론 스타일 메타데이터.
   - primary_signals: 이 영상에서 가장 자주 등장한 신호 3개
   - boolean 4개: top-down, news-driven, chart, foreign flows

5. 한국 종목명은 원문 (예: "삼성전자", "두산에너빌리티", "SK하이닉스", "LG에너지솔루션")
6. 화자 톤 가이드:
   - "꼭 사라" / "확실히 갑니다" → bullish, conviction 5
   - "관심있게 본다" → watch, conviction 2-3
   - "사지 마라" / "지금은 위험" → bearish, conviction 5
7. **uncertain 사용 기준 (엄격)**: 다음 중 하나일 때만 true.
   - 트랜스크립트 길이 5분 미만의 짧은 클립
   - 주식 분석이 아닌 잡담·인사·홍보 영상
   - 트랜스크립트가 깨져서 의미 파악 불가
   정상적으로 분석 가능한 영상이라면 무조건 false. "확신은 없지만 추출은 정상"이면 false.
"""

PRICING = {
    "gpt-5-nano":     {"in": 0.05, "out": 0.40},
    "gpt-5.4-nano":   {"in": 0.05, "out": 0.40},
    "gpt-4.1-nano":   {"in": 0.10, "out": 0.40},
}

def extract(transcript_path: Path, model: str):
    d = json.loads(transcript_path.read_text())
    text = d["full_text"]

    client = OpenAI()
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"제목: {d['title']}\n날짜: {d['upload_date']}\n\n[트랜스크립트]\n{text}"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "theme_extraction_v2", "schema": SCHEMA, "strict": True}
        },
    )
    if model.startswith("gpt-5.4"):
        kwargs["reasoning_effort"] = "none"
    elif model.startswith("gpt-5"):
        kwargs["reasoning_effort"] = "minimal"

    resp = client.chat.completions.create(**kwargs)
    out = json.loads(resp.choices[0].message.content)

    in_tok = resp.usage.prompt_tokens
    out_tok = resp.usage.completion_tokens
    base_model = model.replace("-2025-08-07", "").replace("-2026-03-17", "").replace("-2025-04-14", "")
    pricing = PRICING.get(base_model, PRICING["gpt-5-nano"])
    cost = in_tok * pricing["in"] / 1_000_000 + out_tok * pricing["out"] / 1_000_000

    out["_meta"] = {
        "model": model,
        "video_id": d["video_id"],
        "title": d["title"],
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 6),
    }
    return out


def summarize(result, indent=""):
    m = result["_meta"]
    print(f"{indent}=== {m['model']} ===")
    print(f"{indent}Tokens: in={m['input_tokens']:,} out={m['output_tokens']:,}  Cost: ${m['cost_usd']:.5f}")
    print(f"{indent}View: {result['overall_market_view']}")
    print(f"{indent}Themes ({len(result['themes'])}):")
    for t in result["themes"]:
        sigs = ", ".join(t["discovery_signals"])
        print(f"{indent}  [{t['stance']}/{t['conviction']}|{t['time_horizon']}] {t['name']}")
        print(f"{indent}    signals: {sigs}")
        print(f"{indent}    tickers: {', '.join(t['tickers'][:6])}")
    print(f"{indent}Policy/Diplomatic ({len(result['policy_diplomatic_mentions'])}):")
    for p in result["policy_diplomatic_mentions"]:
        print(f"{indent}  [{p['timing']}|{p['stance']}] {p['event_label']} ({p['event_type']}) → {', '.join(p['expected_impact_sectors'][:4])}")
    mm = result["methodology_meta"]
    print(f"{indent}Methodology: primary={mm['primary_signals']} | top_down={mm['uses_macro_top_down']} news={mm['uses_news_driven']} chart={mm['uses_chart_technical']} foreign={mm['mentions_foreign_flows']}")
    print(f"{indent}Uncertain: {result['uncertain']}")


if __name__ == "__main__":
    transcript = Path(sys.argv[1])
    model = sys.argv[2] if len(sys.argv) > 2 else "gpt-5-nano"
    sys.path.insert(0, str(Path(__file__).parent))
    from config import channel_paths
    out_dir = channel_paths("han_gyunsoo")["extractions"]
    out_dir.mkdir(parents=True, exist_ok=True)

    result = extract(transcript, model)
    out_path = out_dir / f"{transcript.stem}_{model}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    summarize(result)
    print(f"Saved: {out_path}")
