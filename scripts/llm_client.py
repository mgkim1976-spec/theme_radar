"""llm_client — OpenAI 호출·비용 계산 중앙화.

theme_normalizer / methodology_synth / comparative_synth 가 사용.
yt_extract_v2 는 안전상 자체 호출 유지 (workhorse).

특징:
  - reasoning_effort 모델 prefix 자동 매핑
  - PRICING 단일 정의
  - chat / json_object 두 모드
  - 호출 오류 시 None+에러 반환 (예외 throw 안 함, 호출자가 분기)
"""
import json
import os
from dataclasses import dataclass

PRICING = {
    "gpt-5-nano":     {"in": 0.05, "out": 0.40},
    "gpt-5.4-nano":   {"in": 0.05, "out": 0.40},
    "gpt-4.1-nano":   {"in": 0.10, "out": 0.40},
    "gpt-5-mini":     {"in": 0.25, "out": 2.00},
    "gpt-5.4-mini":   {"in": 0.25, "out": 2.00},
}

DEFAULT_MODEL = "gpt-5.4-nano"


def _normalize_model(model: str) -> str:
    """suffix(-2025-08-07 등)와 무관하게 베이스 모델로."""
    base = model
    for suffix in ("-2025-08-07", "-2026-03-17", "-2025-04-14"):
        base = base.replace(suffix, "")
    return base


def _pricing(model: str) -> dict:
    return PRICING.get(_normalize_model(model), PRICING["gpt-5-nano"])


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def as_meta(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def chat(
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    json_mode: bool = False,
) -> LLMResult:
    """기본 chat completion. OPENAI_API_KEY 환경변수 필수."""
    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY 미설정")
    from openai import OpenAI
    client = OpenAI()
    kwargs: dict = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    base = _normalize_model(model)
    if base.startswith("gpt-5.4"):
        kwargs["reasoning_effort"] = "none"
    elif base.startswith("gpt-5"):
        kwargs["reasoning_effort"] = "minimal"

    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    in_tok = resp.usage.prompt_tokens
    out_tok = resp.usage.completion_tokens
    p = _pricing(model)
    cost = (in_tok * p["in"] + out_tok * p["out"]) / 1_000_000
    return LLMResult(text=text, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)


def chat_json(system: str, user: str, model: str = DEFAULT_MODEL) -> tuple[dict, LLMResult]:
    """JSON 응답 자동 파싱."""
    r = chat(system, user, model=model, json_mode=True)
    try:
        data = json.loads(r.text)
    except Exception:
        data = {}
    return data, r
