# guardrails.py - 입력/출력 가드레일 (day5_practice guards_input.py/guards_output.py/
# guards_refusal.py 패턴 재사용). langgraph_supervisor.create_supervisor 그래프는 middleware를
# 받지 않으므로, 이 가드레일은 Supervisor 호출 전/후로 main.py/outer_graph.py에서 직접 호출한다
# (day7_practice/integration_check.py, run_eval.py가 실제로 이렇게 함).
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from config import ROOT_DIR, make_chat_llm  # noqa: E402
from tools.rag_search_tool import get_grounding_sources  # noqa: E402

_GUARD_LLM = make_chat_llm(temperature=0)
AUDIT_LOG_PATH = ROOT_DIR / "guard_audit.log"

INJECTION_PATTERNS = [
    r"ignore (the |all )?(previous|above|prior) (instructions?|prompts?)",
    r"(위의?|이전|기존|지금까지) ?(모든 )?(지시|명령|규칙|프롬프트)[은는를]? ?.{0,8}(무시|잊|버려)",
]

REFUSAL_MESSAGES = {
    "injection": "죄송합니다. 해당 요청은 처리할 수 없습니다. 다른 여행 관련 질문을 해주세요.",
    "off_topic": "죄송합니다. 국내 여행 일정/예산 관련 질문만 도와드릴 수 있습니다.",
    "unsupported_action": (
        "죄송합니다. 항공권/숙소 예약이나 결제를 대신 처리하는 기능은 제공하지 않습니다. "
        "국내 여행 일정 추천과 예산 계산 상담만 도와드릴 수 있어요. "
        "입력하신 개인정보는 저장하거나 다시 노출하지 않습니다."
    ),
    "budget_exceeded": "죄송합니다. 제안된 일정이 입력하신 예산을 초과합니다. 예산을 다시 계산해야 합니다.",
    "hallucination": "죄송합니다. 추천 결과 중 문서에서 확인되지 않는 장소가 있어 다시 확인이 필요합니다.",
}


def _log_block(kind: str, reason: str) -> None:
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} [{kind}] {reason}\n")


def refusal_message(kind: str) -> str:
    return REFUSAL_MESSAGES.get(kind, REFUSAL_MESSAGES["off_topic"])


# ---------- 입력 가드레일 ----------


class RelevanceCheck(BaseModel):
    is_travel_related: bool = Field(description="국내 여행 계획(추천/예산/일정)과 관련된 질문인지")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="판단 이유 한 줄")
    requests_unsupported_action: bool = Field(
        description=(
            "'예약해줘', '대신 결제해줘', '구매해줘'처럼 항공권/숙소 예약·결제·송금·구매를 "
            "실제로 대신 실행해달라고 명시적으로 요청하는 경우에만 true. 가격/정보를 묻기만 "
            "하는 질문(예: '얼마인지 알려줘', '가장 비싼 호텔 알려줘')은 실행 대행 요청이 "
            "아니므로 false다 - 확실하지 않으면 false로 둔다."
        )
    )


def _rule_check(text: str) -> tuple[bool, str]:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, "금지 패턴: 프롬프트 인젝션/지시 무시 시도"
    return False, ""


def _llm_relevance_check(text: str) -> RelevanceCheck:
    checker = _GUARD_LLM.with_structured_output(RelevanceCheck)
    prompt = (
        "다음 사용자 입력이 국내 여행 계획(목적지 추천, 예산 배분, 일정 구성)과 관련된 질문인지 "
        "판단하세요. 인사말이나 여행과 무관한 잡담/업무 질문은 관련 없음(false)입니다. "
        "일반적인 여행 질문은 관련 있음(true)입니다.\n\n"
        "별도로, 이 입력이 항공권/숙소 예약, 결제, 송금처럼 실제 거래를 '대신 실행해달라'고 "
        "명시적으로 요청하는지도 requests_unsupported_action에 표시하세요. 가격이나 정보를 "
        "묻기만 하는 질문(예: '얼마야?', '제일 비싼 호텔 알려줘')은 여기 해당하지 않으므로 "
        "false입니다 - 확실하지 않으면 false로 표시하세요.\n\n"
        f"입력: {text}"
    )
    return checker.invoke(prompt)


def input_guard(text: str) -> tuple[bool, str]:
    """차단 여부와 사유를 반환한다. (blocked, reason)"""
    blocked, reason = _rule_check(text)
    if blocked:
        _log_block("injection", reason)
        return True, "injection"

    try:
        result = _llm_relevance_check(text)
    except Exception as e:
        # LLM 체크 실패 시 fail-open (오탐으로 정상 요청을 막지 않기 위함)
        print(f"[경고] 입력 가드 LLM 체크 실패, 통과 처리: {type(e).__name__}: {e}")
        return False, ""

    if result.requests_unsupported_action:
        reason = f"예약/결제 등 실행 대행 요청 ({result.reason})"
        _log_block("unsupported_action", reason)
        return True, "unsupported_action"

    if not result.is_travel_related and result.confidence > 0.7:
        reason = f"여행과 무관한 질문 ({result.reason})"
        _log_block("off_topic", reason)
        return True, "off_topic"
    return False, ""


# ---------- 출력 가드레일 ----------


class ExtractedPlaces(BaseModel):
    places: list[str] = Field(description="답변에서 추천/언급된 구체적인 장소명 목록 (없으면 빈 리스트)")


def check_grounding(answer: str, query: str) -> tuple[bool, str]:
    """답변에 등장하는 장소명이 실제 RAG 문서(검색 결과)에 존재하는지 문자열 매칭으로 확인한다.

    day2_practice/verify_sources.py의 RunnableParallel(answer=..., sources=...) 아이디어를
    한 단계 더 발전시켜, 실제로 언급된 장소명 자체를 소스 문서 내용과 대조한다.
    """
    sources = get_grounding_sources(query)
    if not sources:
        # 검색 결과 자체가 없다면 recommend_agent가 이미 "찾을 수 없음"으로 답했을 것 -> 통과 처리
        return True, ""

    combined = "\n".join(s["content"] for s in sources)
    extractor = _GUARD_LLM.with_structured_output(ExtractedPlaces)
    try:
        extracted = extractor.invoke(
            f"다음 답변에서 추천/언급된 여행지·맛집·명소 이름만 정확히 추출하세요:\n\n{answer}"
        )
    except Exception as e:
        print(f"[경고] 그라운딩 체크 LLM 호출 실패, 통과 처리: {type(e).__name__}: {e}")
        return True, ""

    missing = [p for p in extracted.places if p and p not in combined]
    if missing:
        reason = f"문서에서 확인되지 않는 장소: {', '.join(missing)}"
        _log_block("hallucination", reason)
        return False, reason
    return True, ""


def check_budget_limit(answer: str, total_budget: int) -> tuple[bool, str]:
    """답변에 총 예산을 초과하는 금액이 노출됐는지 확인하는 이중 안전장치.

    실제 배분 계산은 calculate_budget_allocation 툴이 전담하므로, 여기서는 최종 답변 텍스트에
    잘못된(초과) 숫자가 그대로 노출되지 않았는지 러프하게 재확인만 한다.
    """
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{3,}", answer)]
    over_budget = [n for n in numbers if n > total_budget]
    if over_budget:
        reason = f"총 예산({total_budget:,}원)을 초과하는 금액이 답변에 포함되어 있습니다: {over_budget}"
        _log_block("budget_exceeded", reason)
        return False, reason
    return True, ""
