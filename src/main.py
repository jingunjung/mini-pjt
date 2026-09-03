# main.py - 국내 여행 플래너 CLI 진입점.
# 흐름: 입력 가드레일 -> outer_graph(Supervisor + HITL) 실행 -> interrupt 시 승인/수정/거절 루프
# -> 최종 출력. 체크포인터는 세션 전체를 감싸는 `async with` 블록 안에서 열어둔다
# (reference/day5_practice/hitl_flow.py 패턴 - interrupt/resume에는 열린 연결이 필요하다).
# main.py는 전부 async(ainvoke/aget_state)로 그래프를 호출하므로, 동기 전용인 SqliteSaver가 아니라
# AsyncSqliteSaver/AsyncSqliteStore를 쓴다 (langgraph.checkpoint.sqlite.aio,
# langgraph.store.sqlite.aio, aiosqlite 필요 - requirements.txt 참고). 장기 기억(취향/과거
# 방문지)이 store.sqlite 파일에 영속되므로, 프로그램을 다시 실행해도 같은 user_id로 로그인하면
# 저장된 취향이 그대로 남아 있다.
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402
from langgraph.store.sqlite.aio import AsyncSqliteStore  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agents.supervisor import build_supervisor  # noqa: E402
from config import CHECKPOINT_DB_PATH, RECURSION_LIMIT, STORE_DB_PATH, TASTE_TAGS, TRACE_LOG_PATH  # noqa: E402
from graph.guardrails import input_guard, refusal_message  # noqa: E402
from graph.outer_graph import build_outer_graph  # noqa: E402
from memory.plans import list_plans, plan_summary, save_plan  # noqa: E402
from memory.preferences import get_profile, profile_to_prompt_text, save_profile  # noqa: E402
from tracing.file_tracer import FileTracer  # noqa: E402

tracer = FileTracer(TRACE_LOG_PATH)

# 어느 입력 프롬프트에서든 이 단어를 입력하면 즉시 프로그램을 종료한다 (Ctrl+C도 항상 가능하지만,
# 그건 비정상 종료라 체크포인터 with 블록의 정상 정리를 보장하려면 이쪽이 더 깔끔하다).
EXIT_COMMANDS = {"종료", "exit", "quit"}


class UserExit(Exception):
    """사용자가 EXIT_COMMANDS 중 하나를 입력해 프로그램을 끝내고 싶다는 신호."""


def _check_exit(raw: str) -> None:
    if raw.strip().lower() in EXIT_COMMANDS:
        raise UserExit


def _ask_int(prompt: str, *, min_value: int | None = None, max_value: int | None = None) -> int:
    """숫자가 아니거나 허용 범위를 벗어나면 다시 물어본다 (calculate_budget_allocation의
    Pydantic 제약과 같은 범위를 CLI에서도 미리 걸러, 어차피 실패할 LLM 호출을 줄인다)."""
    while True:
        raw = input(prompt).strip()
        _check_exit(raw)
        raw = raw.replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            print("숫자로 입력해주세요 (예: 600000)")
            continue
        if min_value is not None and value < min_value:
            print(f"{min_value} 이상으로 입력해주세요.")
            continue
        if max_value is not None and value > max_value:
            print(f"{max_value} 이하로 입력해주세요.")
            continue
        return value


def _ask_nonempty(prompt: str) -> str:
    while True:
        raw = input(prompt).strip()
        _check_exit(raw)
        if raw:
            return raw
        print("빈 값은 입력할 수 없습니다. 다시 입력해주세요.")


_DECISION_ALIASES = {
    "a": "approve", "approve": "approve",
    "m": "modify", "modify": "modify",
    "r": "reject", "reject": "reject",
}


def _ask_decision() -> str:
    while True:
        raw = input("승인(approve/A) / 수정(modify/M) / 거절(reject/R) > ").strip()
        _check_exit(raw)
        decision = _DECISION_ALIASES.get(raw.lower())
        if decision:
            return decision
        print("approve(A) / modify(M) / reject(R) 중 하나로만 입력해주세요. (종료하려면 '종료' 입력)")


def _ask_taste_tags() -> list[str]:
    print(f"취향 태그를 선택하세요 (쉼표로 여러 개 가능, 없으면 엔터): {', '.join(TASTE_TAGS)}")
    raw = input("> ").strip()
    _check_exit(raw)
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


async def run_session(checkpointer, store, user_id: str) -> None:
    profile = await get_profile(store, user_id)
    print(f"\n[저장된 취향] {profile_to_prompt_text(profile)}")

    destination = _ask_nonempty("\n어디로 여행 가시나요? (제주/부산/강릉 중 하나 추천): ")
    departure_raw = input("어디서 출발하시나요? (왕복 교통비 추정에 사용, 모르면 엔터): ").strip()
    _check_exit(departure_raw)
    days = _ask_int("여행 기간(일수)을 입력하세요 (1~7): ", min_value=1, max_value=7)
    people = _ask_int("인원수를 입력하세요 (1~10): ", min_value=1, max_value=10)
    total_budget = _ask_int("총 예산(원)을 입력하세요 (0보다 커야 함): ", min_value=1)
    taste_tags = _ask_taste_tags()
    # 이번 세션에서 취향 태그를 안 넣었으면, 저장된 장기 기억의 취향으로 대신 채운다.
    effective_taste_tags = taste_tags or profile.get("taste_tags", [])

    departure_clause = (
        f"출발지: {departure_raw} (왕복 교통비를 추정해서 총 예산에서 미리 제외하고 나머지를 배분해줘). "
        if departure_raw
        else "출발지는 모름 (왕복 교통비는 계산하지 말고 현지 예산만 배분해줘). "
    )
    query = (
        f"{destination} {days}일 여행, 인원 {people}명, 총 예산 {total_budget}원. {departure_clause}"
        f"취향 태그: {', '.join(effective_taste_tags) if effective_taste_tags else '없음'}. "
        "추천 장소, 예산 배분, 일자별 일정표를 모두 만들어줘."
    )
    # 장기 기억(과거 방문지 등)을 실제로 에이전트 컨텍스트에 주입한다 (day7_practice/
    # long_term_memory.py 패턴) - 이전까지는 화면에 참고용으로 보여주기만 하고 실제 질의에는
    # 반영되지 않던 부분을 고쳤다.
    if profile.get("past_destinations"):
        query += f" [참고: 사용자가 과거에 다녀온 곳: {', '.join(profile['past_destinations'])}]"

    print("\n🔎 요청 내용을 확인하는 중입니다...")
    blocked, reason = input_guard(query)
    if blocked:
        print(f"\n{refusal_message(reason)}")
        return

    # 요청마다 Supervisor(및 하위 에이전트)를 새로 지어서 make_chat_llm()의 모델 라운드로빈이
    # 매 요청 실제로 다음 모델로 넘어가게 한다 - 한 번 지어서 프로세스 내내 재사용하면 이
    # 요청에서 저 요청까지 같은 4개 모델에 계속 부하가 몰려 스로틀링 회피 효과가 없다.
    # recommend_agent가 MCP 서버를 서브프로세스로 새로 띄우는 비용(1~2초)이 매번 들지만,
    # 한 요청이 어차피 30~90초 걸리는 걸 감안하면 감수할 만하다.
    print("🤖 에이전트를 준비하는 중입니다...")
    supervisor = await build_supervisor()
    outer_graph = build_outer_graph(supervisor, checkpointer, store)

    thread_id = f"{user_id}:{datetime.now().strftime('%Y%m%d%H%M%S')}"
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "recursion_limit": RECURSION_LIMIT,
        "callbacks": [tracer],
    }
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "total_budget": total_budget,
        "query": query,
        "decision": "",
        "proposal": "",
        "final_answer": "",
    }

    await outer_graph.ainvoke(initial_state, config=config)

    while True:
        state = await outer_graph.aget_state(config)
        if not state.next:
            final_answer = state.values.get("final_answer") or state.values.get("proposal")
            print("\n=== 최종 결과 ===")
            print(final_answer)
            if state.values.get("decision") == "approve":
                await save_profile(store, user_id, taste_tags=taste_tags, past_destination=destination,
                                    budget_range=f"{total_budget}원 내외")
                await save_plan(
                    store, user_id,
                    destination=destination, days=days, people=people,
                    total_budget=total_budget, taste_tags=effective_taste_tags,
                    itinerary=final_answer,
                )
                print("\n✅ 이 계획을 장기 기억에 저장했습니다. 다음에 시작할 때 다시 볼 수 있습니다.")
            return

        interrupt_payload = state.tasks[0].interrupts[0].value
        print("\n=== 제안된 여행 계획 ===")
        print(interrupt_payload["proposal"])
        print(f"\n{interrupt_payload['question']}")
        decision = _ask_decision()

        resume: dict = {"decision": decision}
        if decision == "modify":
            resume["feedback"] = _ask_nonempty("수정 요청 사항을 입력하세요: ")
        elif decision == "reject":
            reason_raw = input("거절 사유를 입력하세요 (선택, 엔터로 건너뛰기): ").strip()
            _check_exit(reason_raw)
            resume["reason"] = reason_raw or "사유 없음"

        await outer_graph.ainvoke(Command(resume=resume), config=config)


async def show_saved_plans(store, user_id: str) -> None:
    plans = await list_plans(store, user_id)
    if not plans:
        print("저장된 계획이 없습니다.")
        return

    while True:
        print("\n=== 저장된 여행 계획 ===")
        for i, plan in enumerate(plans, start=1):
            print(f"{i}. {plan_summary(plan)}")
        raw = input("자세히 볼 번호를 입력하세요 (돌아가려면 엔터): ").strip()
        _check_exit(raw)
        if not raw:
            return
        try:
            idx = int(raw)
        except ValueError:
            print("숫자로 입력해주세요.")
            continue
        if not (1 <= idx <= len(plans)):
            print(f"1~{len(plans)} 사이의 번호를 입력해주세요.")
            continue

        chosen = plans[idx - 1]
        print(f"\n=== {plan_summary(chosen)} ===")
        print(chosen["itinerary"])

        again = input("\n다른 저장된 계획을 더 보시겠어요? (y/n): ").strip().lower()
        if again != "y":
            return


async def main_menu(checkpointer, store, user_id: str) -> None:
    while True:
        plans = await list_plans(store, user_id)
        print(f"\n저장된 여행 계획: {len(plans)}건")
        print("1) 새 계획 세우기")
        if plans:
            print("2) 저장된 계획 보기")
        raw = input("번호를 선택하세요 (종료하려면 '종료'): ").strip()
        _check_exit(raw)

        if raw == "1" or (not plans and raw == ""):
            await run_session(checkpointer, store, user_id)
        elif raw == "2" and plans:
            await show_saved_plans(store, user_id)
        else:
            print("1 또는 2를 입력해주세요.")
            continue

        again = input("\n메뉴로 돌아갈까요? (y/n, n을 누르면 종료): ").strip().lower()
        if again != "y":
            return


INTRO = """\
=== 국내 여행 플래너 ===
총 예산과 취향을 알려주시면 아래 세 가지를 한 번에 만들어 드립니다.
  1. 추천 - 실제 관광 데이터에 근거한 여행지/맛집/숙소/숨은명소 (출처 표기)
  2. 예산 배분 - 숙박/식비/현지교통/관광 항목별 자동 배분 (총 예산 절대 초과 없음)
     ※ 출발지를 알려주시면 왕복 교통비(항공권/KTX 등 서울-부산/서울-강릉/제주행 항공만
       지원)를 추정해 총 예산에서 먼저 빼고 나머지를 배분합니다. 모르는 노선이거나
       출발지를 안 알려주시면 현지 비용만 배분합니다.
  3. 일정표 - 일자별 시간표 (시간 겹침·동선 자동 검증)
완성된 계획은 최종 확정 전에 승인(approve)/수정(modify)/거절(reject)로 확인을 받고,
승인된 계획은 장기 기억에 저장되어 다음에 실행할 때도 다시 꺼내볼 수 있습니다.
어느 입력창에서든 '종료'를 입력하면 언제든 프로그램을 끝낼 수 있습니다.
"""


async def main() -> None:
    print(INTRO)
    try:
        user_id = input("사용자 ID를 입력하세요 (예: guest): ").strip()
        _check_exit(user_id)
        user_id = user_id or "guest"

        async with (
            AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer,
            AsyncSqliteStore.from_conn_string(STORE_DB_PATH) as store,
        ):
            await checkpointer.setup()
            await store.setup()
            await main_menu(checkpointer, store, user_id)
    except UserExit:
        pass

    print("\n이용해주셔서 감사합니다.")


if __name__ == "__main__":
    asyncio.run(main())
