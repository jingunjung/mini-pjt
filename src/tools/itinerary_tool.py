# itinerary_tool.py - 일정표의 시간 겹침과 동선(지역) 정합성을 결정적으로 검증하는 툴.
# 실제 경로 API 없이 "같은 날 활동은 같은 지역이어야 자연스럽다"는 휴리스틱으로 동선을 체크한다.
# reference/day4_practice/tool_error.py 패턴대로 에러/검증 실패는 예외 대신 결과 문자열로 반환한다.
import json
from datetime import datetime

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class Activity(BaseModel):
    time_start: str = Field(description="시작 시각, 'HH:MM' 형식 (예: '09:00')")
    time_end: str = Field(description="종료 시각, 'HH:MM' 형식 (예: '11:00')")
    place: str = Field(description="장소명")
    region: str = Field(description="지역명 (예: '제주', '부산')")


class DayPlan(BaseModel):
    day: int = Field(ge=1, description="여행 몇 일차인지 (1부터 시작)")
    activities: list[Activity]


class ItineraryInput(BaseModel):
    days: list[DayPlan] = Field(description="일자별 활동 목록")


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M")


@tool(
    "validate_itinerary",
    description=(
        "일자별 일정표의 시간 겹침과 동선(지역 일관성)을 검증한다. "
        "각 Day 안의 활동 시간대가 겹치지 않는지, 같은 날 활동이 같은 지역 안에 있는지 확인한다. "
        "일정표를 최종 확정하기 전에 반드시 이 도구로 검증한다."
    ),
    args_schema=ItineraryInput,
)
def validate_itinerary(days: list[dict]) -> str:
    # args_schema(ItineraryInput)가 이미 각 항목을 DayPlan으로 검증/변환해서 넘겨줄 수도 있고,
    # 원본 dict 그대로 넘어올 수도 있어(LangChain 버전에 따라 동작이 다름) 둘 다 받아들인다.
    try:
        parsed_days = [d if isinstance(d, DayPlan) else DayPlan(**d) for d in days]
    except Exception as e:
        return f"에러: 일정 형식이 올바르지 않습니다 ({type(e).__name__}: {e}). 스키마를 확인하세요."

    issues: list[str] = []

    for day in parsed_days:
        if not day.activities:
            issues.append(f"{day.day}일차: 활동이 비어 있습니다.")
            continue

        # 1) 시간 파싱 + 정렬
        try:
            sorted_acts = sorted(day.activities, key=lambda a: _parse_time(a.time_start))
        except ValueError as e:
            issues.append(f"{day.day}일차: 시간 형식 오류 ({e}). 'HH:MM' 형식으로 입력하세요.")
            continue

        # 2) 시간 겹침 체크
        for prev, cur in zip(sorted_acts, sorted_acts[1:]):
            prev_end = _parse_time(prev.time_end)
            cur_start = _parse_time(cur.time_start)
            if cur_start < prev_end:
                issues.append(
                    f"{day.day}일차: '{prev.place}'({prev.time_start}-{prev.time_end})와 "
                    f"'{cur.place}'({cur.time_start}-{cur.time_end}) 시간이 겹칩니다."
                )

        # 3) 동선(지역 일관성) 체크
        regions = {a.region for a in day.activities}
        if len(regions) > 1:
            issues.append(
                f"{day.day}일차: 서로 다른 지역({', '.join(sorted(regions))})을 하루에 이동합니다. "
                "동선이 비효율적일 수 있으니 지역별로 날짜를 나누는 것을 검토하세요."
            )

    result = {"valid": len(issues) == 0, "issues": issues}
    return json.dumps(result, ensure_ascii=False)
