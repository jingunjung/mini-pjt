# plans.py - 승인된 여행 계획 전체를 사용자별 장기 기억(Store)에 저장/조회한다.
# preferences.py가 "취향 요약"을 저장한다면, 이 모듈은 "확정된 일정 원문 전체"를 저장해
# 프로그램을 다시 켜도 지난 계획을 그대로 다시 볼 수 있게 한다.
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

PLANS_NAMESPACE_SUFFIX = "plans"


def _namespace(user_id: str) -> tuple[str, ...]:
    return ("users", user_id, PLANS_NAMESPACE_SUFFIX)


async def save_plan(
    store: BaseStore,
    user_id: str,
    *,
    destination: str,
    days: int,
    people: int,
    total_budget: int,
    taste_tags: list[str],
    itinerary: str,
) -> str:
    """승인된 여행 계획을 저장하고 생성된 plan_id를 반환한다."""
    plan_id = datetime.now().strftime("%Y%m%d%H%M%S")
    plan = {
        "destination": destination,
        "days": days,
        "people": people,
        "total_budget": total_budget,
        "taste_tags": taste_tags,
        "itinerary": itinerary,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    await store.aput(_namespace(user_id), plan_id, plan)
    return plan_id


async def list_plans(store: BaseStore, user_id: str, limit: int = 20) -> list[dict]:
    """저장된 계획을 최신순으로 반환한다. 각 dict에 'plan_id' 키가 포함된다."""
    items = await store.asearch(_namespace(user_id), limit=limit)
    plans = []
    for item in items:
        plan = dict(item.value)
        plan["plan_id"] = item.key
        plans.append(plan)
    plans.sort(key=lambda p: p.get("approved_at", ""), reverse=True)
    return plans


def plan_summary(plan: dict) -> str:
    taste = ", ".join(plan.get("taste_tags") or []) or "없음"
    approved_at = (plan.get("approved_at") or "?")[:19].replace("T", " ")
    return (
        f"{plan['destination']} {plan['days']}일 / 인원 {plan['people']}명 / "
        f"예산 {plan['total_budget']:,}원 / 취향: {taste} (승인: {approved_at})"
    )
