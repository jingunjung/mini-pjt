# budget_agent.py - 예산 전문가: 예산 계산/배분만 담당한다 (계산은 항상 tool에 위임).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain.agents import create_agent  # noqa: E402

from config import make_chat_llm  # noqa: E402
from tools.budget_tool import calculate_budget_allocation  # noqa: E402
from tools.transport_tool import estimate_round_trip_transport  # noqa: E402

BUDGET_SYSTEM_PROMPT = (
    "너는 여행 예산 전문가다. 총 예산을 항목별(숙박/식비/현지교통/관광)로 배분하는 계산만\n"
    "담당한다. 숫자 계산은 절대 직접 하지 말고 반드시 도구를 호출해서 얻어라.\n"
    "\n"
    "[처리 순서]\n"
    "1. 요청에 출발지가 있으면 먼저 estimate_round_trip_transport(출발지, 목적지, 인원)를\n"
    "   호출해 왕복 교통비를 추정하라. known이 false면 왕복 교통비는 모르는 것으로 처리하고,\n"
    "   known이 true면 그 결과의 '왕복_추정_전체인원'(제주는 '왕복_추정_평시_전체인원') 금액을\n"
    "   기억해둔다. 출발지가 없으면 이 단계를 건너뛴다.\n"
    "2. calculate_budget_allocation을 호출한다. 1단계에서 구한 왕복 교통비가 있으면\n"
    "   round_trip_transport_cost 인자에 그대로 넣고, 없으면 0(기본값)으로 둔다.\n"
    "3. 도구 결과를 그대로 인용해 (a) 왕복 교통비 추정치(있으면, 추정치라는 점도 함께),\n"
    "   (b) 현지 예산 배분 내역, (c) 합계 검증을 정리해 보고한다. 도구 결과의 note 필드는\n"
    "   반드시 답변에 그대로 포함하라 - 빠뜨리면 사용자가 예산 범위를 오해한다.\n"
    "\n"
    "장소 추천이나 일정 시간 배치는 담당 범위가 아니므로 다루지 마라."
)


def build_budget_agent():
    llm = make_chat_llm(temperature=0)
    return create_agent(
        llm,
        [calculate_budget_allocation, estimate_round_trip_transport],
        system_prompt=BUDGET_SYSTEM_PROMPT,
        name="budget_agent",
    )
