# itinerary_agent.py - 일정 전문가: 일자별 일정표 구성 및 시간/동선 검증만 담당한다.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain.agents import create_agent  # noqa: E402

from config import make_chat_llm  # noqa: E402
from tools.itinerary_tool import validate_itinerary  # noqa: E402

ITINERARY_SYSTEM_PROMPT = (
    "너는 여행 일정 전문가다. 주어진 장소 목록과 기간을 바탕으로 일자별 시간표를 구성한다.\n"
    "일정을 확정하기 전에 반드시 validate_itinerary 도구로 시간 겹침과 동선(지역 일관성)을\n"
    "검증하고, 문제(issues)가 있으면 일정을 수정해 다시 검증하라. valid가 true일 때만 최종\n"
    "일정표로 제시하라. 장소 추천이나 예산 계산은 담당 범위가 아니므로 다루지 마라."
)


def build_itinerary_agent():
    llm = make_chat_llm(temperature=0)
    return create_agent(
        llm,
        [validate_itinerary],
        system_prompt=ITINERARY_SYSTEM_PROMPT,
        name="itinerary_agent",
    )
