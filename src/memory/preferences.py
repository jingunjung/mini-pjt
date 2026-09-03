# preferences.py - 사용자 취향(taste_tags)을 세션(thread_id)과 무관하게 기억하는 장기 기억.
# reference/day7_practice/long_term_memory.py의 Store 패턴을 따르되, main.py가 재실행돼도
# 기억이 남도록 영속 저장소(AsyncSqliteStore)를 쓴다 - 그래서 aget/aput(비동기)만 쓴다.
# thread_id(체크포인터, 세션 단위) vs user_id(store, 영구)가 서로 다른 개념임에 유의.
from langgraph.store.base import BaseStore

NAMESPACE_KEY = "profile"


async def get_profile(store: BaseStore, user_id: str) -> dict:
    item = await store.aget(("users", user_id), NAMESPACE_KEY)
    if item is None:
        return {"taste_tags": [], "past_destinations": [], "budget_range": None}
    return item.value


async def save_profile(store: BaseStore, user_id: str, *, taste_tags: list[str] | None = None,
                        past_destination: str | None = None, budget_range: str | None = None) -> dict:
    profile = await get_profile(store, user_id)
    if taste_tags:
        profile["taste_tags"] = sorted(set(profile.get("taste_tags", [])) | set(taste_tags))
    if past_destination:
        destinations = profile.get("past_destinations", [])
        if past_destination not in destinations:
            destinations.append(past_destination)
        profile["past_destinations"] = destinations
    if budget_range:
        profile["budget_range"] = budget_range
    await store.aput(("users", user_id), NAMESPACE_KEY, profile)
    return profile


def profile_to_prompt_text(profile: dict) -> str:
    if not profile.get("taste_tags") and not profile.get("past_destinations"):
        return "저장된 취향 정보 없음"
    parts = []
    if profile.get("taste_tags"):
        parts.append(f"선호 취향: {', '.join(profile['taste_tags'])}")
    if profile.get("past_destinations"):
        parts.append(f"과거 방문지: {', '.join(profile['past_destinations'])}")
    if profile.get("budget_range"):
        parts.append(f"평소 예산대: {profile['budget_range']}")
    return " / ".join(parts)
