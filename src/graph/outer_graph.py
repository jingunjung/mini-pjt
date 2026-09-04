# outer_graph.py - Supervisor를 감싸는 외곽 LangGraph.
# plan_trip(Supervisor 서브그래프 호출) -> human_approval(interrupt, day5_practice/hitl_flow.py
# 패턴) -> 승인/수정/거절 3분기. 체크포인터(SqliteSaver)와 장기기억(Store)은 main.py에서 생성해
# build_outer_graph()에 주입한다 (SqliteSaver.from_conn_string은 context manager라 CLI 세션
# 전체를 감싸는 `with` 블록이 main.py에 있어야 한다).
import asyncio
import itertools
import sys
from pathlib import Path
from typing import Annotated, Literal, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.types import interrupt  # noqa: E402

from config import RECURSION_LIMIT  # noqa: E402
from graph.guardrails import check_budget_limit, check_grounding  # noqa: E402
from utils import get_final_answer  # noqa: E402


class PlannerState(TypedDict):
    messages: Annotated[list, add_messages]
    total_budget: int
    query: str
    proposal: str
    decision: str
    final_answer: str


# Supervisor가 몇 초~몇 분씩 걸릴 수 있어서(에이전트 3개를 순서대로 호출), ainvoke로 한 번에
# 기다리면 CLI에 아무 표시가 없어 멈춘 것처럼 보인다. astream(stream_mode="values")로 바꿔서
# 진행 상황(몇 단계 중 몇 단계, 어떤 에이전트가 도는 중인지)을 회전 스피너와 함께 보여준다.
# stream_mode="values"는 매 스텝마다 "누적된 전체 상태"를 내보내므로, 마지막으로 받은 값이
# ainvoke의 반환값과 동일하다.
#
# langgraph_supervisor는 에이전트를 호출할 때 ToolMessage(name="transfer_to_<agent>")로 핸드오프를
# 시작하고, 그 에이전트가 실제 내용이 담긴 AIMessage(name="<agent>", tool_calls 없음)를 낸 뒤
# ToolMessage(name="transfer_back_to_supervisor")로 복귀한다 (실제 스트림으로 확인한 메시지 순서).
# 이 신호를 이용해 "지금 몇 번째 단계가 진행 중인지"를 정확히 알 수 있다.
TOTAL_STEPS = 3
_TRANSFER_TO_STEP = {
    "transfer_to_recommend_agent": (1, "🔍 추천 에이전트 - 여행지/맛집 검색 중"),
    "transfer_to_budget_agent": (2, "💰 예산 에이전트 - 예산 배분 계산 중"),
    "transfer_to_itinerary_agent": (3, "🗓️ 일정 에이전트 - 일정표 생성/검증 중"),
}
_AGENT_DONE_LABEL = {
    "recommend_agent": "🔍 추천 에이전트 완료",
    "budget_agent": "💰 예산 에이전트 완료",
    "itinerary_agent": "🗓️ 일정 에이전트 완료",
}
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _Spinner:
    """터미널 한 줄에 회전 스피너 + 현재 단계 라벨을 그리는 헬퍼.

    label을 바꾸면 다음 프레임부터 바뀐 텍스트가 표시된다. 완료 메시지처럼 스피너 줄 위에
    한 줄을 확정해서 남기고 싶을 때는 print_line()을 쓴다 (스피너 줄을 지우고 출력한 뒤,
    다음 프레임부터 같은 자리에 다시 스피너가 돈다).
    """

    def __init__(self):
        self.label = ""
        self._task: asyncio.Task | None = None
        self._frames = itertools.cycle(_SPINNER_FRAMES)

    def set_label(self, label: str) -> None:
        self.label = label

    def _clear(self) -> None:
        # "\r"은 커서를 줄 맨 앞으로 되돌릴 뿐 아무것도 지우지 않는다. 이전에 공백으로
        # 패딩해서 지우려 했지만, 라벨에 한글/이모지가 섞여 있으면 터미널에서 한 글자가
        # 2칸을 차지해 len() 기준 패딩 폭이 실제 화면 폭보다 모자라 꼬리 문자가 남았다.
        # "커서~줄 끝까지 지우기" ANSI 명령(\x1b[K)을 쓰면 문자 폭 계산 없이 항상 정확히
        # 지워진다.
        print("\r\x1b[K", end="", flush=True)

    def print_line(self, text: str) -> None:
        self._clear()
        print(text)

    async def _run(self) -> None:
        while True:
            text = f"{next(self._frames)} {self.label}"
            print(f"\r\x1b[K{text}", end="", flush=True)
            await asyncio.sleep(0.1)

    async def __aenter__(self) -> "_Spinner":
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._clear()


def _make_plan_trip_node(supervisor):
    async def plan_trip(state: PlannerState) -> dict:
        print(f"\n⏳ 여행 계획을 생성하는 중입니다 (총 {TOTAL_STEPS}단계: 추천 → 예산 → 일정)")
        seen = 0
        completed = 0
        final_state = None

        async with _Spinner() as spinner:
            spinner.set_label(f"[0/{TOTAL_STEPS}] 요청을 분석하고 담당 에이전트를 결정하는 중")
            async for value in supervisor.astream(
                {"messages": state["messages"]},
                config={"recursion_limit": RECURSION_LIMIT},
                stream_mode="values",
            ):
                final_state = value
                messages = value.get("messages", [])
                for msg in messages[seen:]:
                    name = getattr(msg, "name", None)
                    if name in _TRANSFER_TO_STEP:
                        step, label = _TRANSFER_TO_STEP[name]
                        spinner.set_label(f"[{step}/{TOTAL_STEPS}] {label}")
                    elif name in _AGENT_DONE_LABEL and msg.content and not getattr(msg, "tool_calls", None):
                        spinner.print_line(f"✅ {_AGENT_DONE_LABEL[name]}")
                        completed += 1
                        if completed == TOTAL_STEPS:
                            spinner.set_label("📝 세 에이전트 결과를 종합하는 중")
                seen = len(messages)

        if final_state is None:
            raise RuntimeError("Supervisor가 결과를 반환하지 않았습니다.")

        print("🔎 가드레일 검증 중...")
        proposal = get_final_answer(final_state["messages"])

        grounded, ground_reason = check_grounding(proposal, state["query"])
        if not grounded:
            proposal += f"\n\n[안내: {ground_reason}]"

        budget_ok, budget_reason = check_budget_limit(proposal, state["total_budget"])
        if not budget_ok:
            proposal += f"\n\n[안내: {budget_reason}]"

        return {"proposal": proposal}

    return plan_trip


def human_approval(state: PlannerState) -> dict:
    answer = interrupt(
        {
            "proposal": state["proposal"],
            "question": "이 여행 계획을 승인(approve/A) / 수정(modify/M) / 거절(reject/R) 하시겠습니까?",
        }
    )
    decision = answer.get("decision", "reject")

    if decision == "approve":
        return {"decision": decision, "final_answer": state["proposal"]}

    if decision == "modify":
        feedback = answer.get("feedback", "").strip()
        note = f"다음 피드백을 반영해서 여행 계획을 다시 세워줘: {feedback}" if feedback else "계획을 다시 검토해줘."
        return {"decision": decision, "messages": [HumanMessage(content=note)]}

    reason = answer.get("reason", "사유 없음")
    return {"decision": "reject", "final_answer": f"사용자가 계획을 거절했습니다. 사유: {reason}"}


def _route_after_approval(state: PlannerState) -> Literal["plan_trip", "__end__"]:
    return "plan_trip" if state["decision"] == "modify" else "__end__"


def build_outer_graph(supervisor, checkpointer, store):
    builder = StateGraph(PlannerState)
    builder.add_node("plan_trip", _make_plan_trip_node(supervisor))
    builder.add_node("human_approval", human_approval)
    builder.add_edge(START, "plan_trip")
    builder.add_edge("plan_trip", "human_approval")
    builder.add_conditional_edges(
        "human_approval", _route_after_approval, {"plan_trip": "plan_trip", "__end__": END}
    )
    return builder.compile(checkpointer=checkpointer, store=store)
