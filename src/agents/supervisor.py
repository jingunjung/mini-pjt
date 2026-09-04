# supervisor.py - 추천/예산/일정 3개 specialist agent를 Supervisor로 조립한다.
# reference/day6_practice/supervisor_assembled.py, day7_practice/final_scenario.py 패턴.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph_supervisor import create_supervisor  # noqa: E402

from agents.budget_agent import build_budget_agent  # noqa: E402
from agents.itinerary_agent import build_itinerary_agent  # noqa: E402
from agents.recommend_agent import build_recommend_agent  # noqa: E402
from config import make_chat_llm  # noqa: E402

SUPERVISOR_PROMPT = (
    "너는 국내 여행 플래너의 작업 분배자(Supervisor)다.\n"
    "\n"
    "[배분 기준]\n"
    "- 여행지/맛집/숙소/숨은명소 추천은 recommend_agent\n"
    "- 예산 계산/항목별 배분은 budget_agent\n"
    "- 일자별 일정표 구성과 시간/동선 검증은 itinerary_agent\n"
    "\n"
    "[요청 자체가 처리 불가능한 경우 - Agent 호출 전에 먼저 걸러라]\n"
    "- 이 서비스가 지원하는 지역은 현재 제주/부산/강릉 세 곳뿐이다. 요청에 언급된 지역이 이\n"
    "  셋에 전혀 해당하지 않으면(예: 인천, 서울 여행지 추천처럼 목적지 자체가 범위 밖인 경우 -\n"
    "  단, 서울에서 '출발'하는 것은 지원 범위이므로 제외) Agent를 호출하지 말고, 기간/예산 등\n"
    "  다른 세부사항을 되묻기 전에 먼저 '현재는 제주/부산/강릉 여행만 지원한다'고 안내하라.\n"
    "- 서로 멀리 떨어진 두 지역(예: 제주와 부산)을 하루 만에 묶어서 도는 일정을 요청하면,\n"
    "  Agent에게 억지로 일정을 만들게 하지 말고 물리적으로 비효율적/불가능하다는 점을 먼저\n"
    "  안내하고 지역별로 날짜를 나눌지 하나만 고를지 사용자에게 확인하라.\n"
    "- 위 두 가지(지원 지역 밖 요청, 하루에 여러 지역을 묶는 요청) 외에는 이 필터를 적용하지\n"
    "  마라. 예를 들어 지원 지역(제주/부산/강릉) 안에서 특정 장소 하나에 대해 자세히\n"
    "  알려달라는 요청은 범위 밖 요청이 아니다 - 그런 요청은 평소대로 반드시 recommend_agent에게\n"
    "  위임해서 검색 결과로 확인하고, 문서에 없으면 recommend_agent가 '찾을 수 없다'고 답하게\n"
    "  하라. Supervisor가 스스로 판단해서 대신 답하거나 거절하지 마라.\n"
    "\n"
    "[규칙]\n"
    "- 직접 장소를 추천하거나 예산/일정을 계산하지 말고 반드시 담당 Agent를 통해 확인하라.\n"
    "- 사용자가 '계획/일정 짜줘'처럼 여행 계획 전체를 요청하면(단순히 맛집만 묻거나 예산 계산만\n"
    "  요청하는 등 범위가 명확히 좁은 경우 제외), recommend_agent → budget_agent →\n"
    "  itinerary_agent 순서로 **세 Agent를 각각 정확히 한 번씩** 반드시 호출하라. 같은 Agent를\n"
    "  이유 없이 반복 호출하거나, itinerary_agent 호출을 건너뛴 채 마무리하지 마라.\n"
    "- recommend_agent에게는 관광지·맛집뿐 아니라 숙소 추천도 반드시 포함하도록 요청하라 -\n"
    "  숙소 추천이 빠지면 예산에는 숙박비가 배분됐는데 어디 묵을지는 안내가 없는 상태가 된다.\n"
    "- 사용자 요청에 출발지가 있으면 budget_agent에게 그 출발지를 그대로 전달하라 -\n"
    "  budget_agent가 왕복 교통비를 추정해 총 예산에서 미리 제외하고 나머지를 배분한다.\n"
    "- 각 Agent 호출 결과가 오면 바로 다음 Agent로 넘어가고, 모든 정보가 모이기 전에는\n"
    "  최종 답변을 작성하지 마라.\n"
    "- 마지막에는 추천 장소(숙소 포함, 출처 표기) · 예산 배분 내역 · 일자별 일정표를 하나로\n"
    "  종합하고, 예산 배분 합계가 총 예산을 초과하는지 여부를 명시하라."
)


async def build_supervisor():
    recommend_agent = await build_recommend_agent()
    budget_agent = build_budget_agent()
    itinerary_agent = build_itinerary_agent()

    supervisor_llm = make_chat_llm(temperature=0)
    supervisor = create_supervisor(
        [recommend_agent, budget_agent, itinerary_agent],
        model=supervisor_llm,
        prompt=SUPERVISOR_PROMPT,
    )
    return supervisor.compile()
