# budget_tool.py - 예산 계산/배분을 담당하는 결정적 계산 툴.
# LLM이 산술을 직접 하면 큰 숫자에서 오류(환각)를 내기 쉬우므로, 반드시 이 파이썬 함수가
# 계산을 전담하고 Agent는 결과를 인용만 하도록 한다.
# reference/day4_practice/tools_basic.py (Level3: args_schema)와
# reference/day4_practice/tool_error.py (에러는 raise 대신 문자열로 반환) 패턴을 따른다.
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# 기본 배분 비율 (합계 1.0)
BASE_WEIGHTS = {"숙박": 0.35, "식비": 0.30, "교통": 0.20, "관광": 0.15}

# 취향 태그별 가중치 보정값 (항목: %p 증감). 여러 태그가 섞이면 누적 적용된다.
TASTE_ADJUSTMENTS = {
    "맛집중심": {"식비": +0.10, "관광": -0.05, "숙박": -0.05},
    "숨은여행지": {"관광": +0.08, "교통": +0.07, "식비": -0.05, "숙박": -0.10},
    "액티비티중심": {"관광": +0.15, "식비": -0.05, "숙박": -0.05, "교통": -0.05},
    "편안한숙소": {"숙박": +0.15, "관광": -0.10, "식비": -0.05},
}


def _adjust_weights(taste_tags: list[str]) -> dict[str, float]:
    weights = dict(BASE_WEIGHTS)
    for tag in taste_tags:
        delta = TASTE_ADJUSTMENTS.get(tag.strip())
        if not delta:
            continue
        for category, amount in delta.items():
            weights[category] = weights.get(category, 0.0) + amount
    # 음수 방지 후 합계 1.0으로 재정규화
    weights = {k: max(v, 0.0) for k, v in weights.items()}
    total_weight = sum(weights.values()) or 1.0
    return {k: v / total_weight for k, v in weights.items()}


def _allocate(total_budget: int, weights: dict[str, float]) -> dict[str, int]:
    allocation = {k: round(total_budget * w) for k, w in weights.items()}
    # 반올림 오차 보정: 합계가 총액과 다르면 가장 비중이 큰 항목에서 차액을 흡수한다.
    diff = total_budget - sum(allocation.values())
    if diff != 0:
        biggest = max(allocation, key=allocation.get)
        allocation[biggest] += diff
    return allocation


class BudgetInput(BaseModel):
    total_budget: int = Field(gt=0, description="총 여행 예산 (원)")
    days: int = Field(ge=1, le=7, description="여행 일수")
    people: int = Field(ge=1, le=10, description="인원수")
    taste_tags: list[str] = Field(
        default_factory=list,
        description="취향 태그 목록. 사용 가능한 값: 맛집중심, 숨은여행지, 액티비티중심, 편안한숙소",
    )
    round_trip_transport_cost: int = Field(
        default=0,
        ge=0,
        description=(
            "출발지~목적지 왕복 교통비(원). estimate_round_trip_transport 도구 결과의 "
            "왕복 추정 금액을 그대로 넣는다. 모르거나 계산하지 않았으면 0."
        ),
    )


@tool(
    "calculate_budget_allocation",
    description=(
        "총 예산에서 왕복 교통비(있으면)를 먼저 제외한 뒤, 남은 금액을 숙박/식비/현지교통/관광 "
        "4개 항목으로 자동 배분한다. 취향 태그(맛집중심/숨은여행지/액티비티중심/편안한숙소)를 "
        "반영해 가중치를 조정한다. 출발지가 있으면 먼저 estimate_round_trip_transport로 왕복 "
        "교통비를 구해 round_trip_transport_cost에 넣어라 - 모르면 0으로 둔다(이 경우 배분은 "
        "현지 비용만 다룬다는 note가 함께 온다). "
        "예산과 관련된 모든 숫자 계산은 반드시 이 도구를 통해서만 하고, LLM이 직접 계산하지 않는다."
    ),
    args_schema=BudgetInput,
)
def calculate_budget_allocation(
    total_budget: int, days: int, people: int, taste_tags: list[str], round_trip_transport_cost: int = 0
) -> str:
    try:
        if round_trip_transport_cost >= total_budget:
            return (
                f"에러: 왕복 교통비({round_trip_transport_cost}원)가 총 예산({total_budget}원) "
                "이상입니다. 총 예산을 늘리거나 교통편을 재검토해야 합니다."
            )

        local_budget = total_budget - round_trip_transport_cost
        unknown_tags = [t for t in taste_tags if t.strip() not in TASTE_ADJUSTMENTS]
        weights = _adjust_weights(taste_tags)
        allocation = _allocate(local_budget, weights)

        if sum(allocation.values()) != local_budget:
            return (
                f"에러: 예산 배분 합계({sum(allocation.values())}원)가 현지 예산({local_budget}원)과 "
                "일치하지 않습니다. 다시 계산해 주세요."
            )

        if round_trip_transport_cost > 0:
            note = (
                f"왕복 교통비 {round_trip_transport_cost:,}원을 총 예산에서 미리 제외했고, "
                f"남은 {local_budget:,}원을 현지 항목(숙박/식비/현지교통/관광)으로 배분했습니다. "
                "왕복 교통비는 추정치이므로 실제 예약 시점 요금과 다를 수 있습니다."
            )
        else:
            note = (
                "왕복 교통비를 알 수 없어 이 배분은 목적지 내 현지 이동(렌터카/택시/버스 등) "
                "비용만 포함합니다. 출발지~목적지 왕복 교통비(항공권/KTX 등)는 별도로 확보하세요."
            )

        result = {
            "total_budget": total_budget,
            "round_trip_transport_cost": round_trip_transport_cost,
            "local_budget": local_budget,
            "days": days,
            "people": people,
            "taste_tags": taste_tags,
            "unknown_taste_tags": unknown_tags,
            "allocation": allocation,
            "per_day_average": round(local_budget / days),
            "per_person_average": round(local_budget / people),
            "note": note,
        }
        return json.dumps(result, ensure_ascii=False)
    except ZeroDivisionError:
        return "에러: 일수(days)와 인원수(people)는 1 이상이어야 합니다."
    except Exception as e:
        return f"에러: 예산 계산 중 문제가 발생했습니다 ({type(e).__name__}). 입력값을 확인 후 다시 시도하세요."
