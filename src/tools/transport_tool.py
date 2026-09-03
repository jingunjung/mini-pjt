# transport_tool.py - 출발지~목적지 왕복 교통비를 추정하는 결정적 계산 툴.
# 실시간 항공/철도 요금 API가 없으므로, 조사 시점(2026년) 공개된 대표 요금을 하드코딩한
# 조회 테이블로 "추정치"를 제공한다. 모르는 노선은 절대 지어내지 않고 "정보 없음"으로 답한다
# (reference/day4_practice/tool_error.py의 "모르면 에러/안내 문자열을 반환" 패턴과 같은 원칙).
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# KTX 등 고정 노선 요금(편도, 성인 기준 원) - 코레일 공지 요금으로 비교적 안정적이다.
# 조사 시점 기준이며 실제 요금은 코레일/항공사 사이트에서 재확인을 권장한다.
FIXED_ROUTE_FARES = {
    ("서울", "부산"): {"편도": 59_800, "수단": "KTX"},
    ("서울", "강릉"): {"편도": 27_600, "수단": "KTX (청량리 기준)"},
}

# 제주는 사실상 항공편 없이는 갈 수 없어 출발지에 상관없이 항공권 시세 범위로 안내한다.
# 저비용항공사 기준 평시 편도, 성수기(7월 중순~8월 말)에는 15만원까지도 오른다.
JEJU_FLIGHT_FARE_RANGE = {"편도_최저": 30_000, "편도_평시": 70_000, "편도_성수기": 150_000}


class TransportInput(BaseModel):
    departure: str = Field(description="출발지(도시명), 예: '서울', '부산'")
    destination: str = Field(description="목적지, '제주'/'부산'/'강릉' 중 하나")
    people: int = Field(ge=1, le=10, description="인원수")


@tool(
    "estimate_round_trip_transport",
    description=(
        "출발지에서 목적지까지의 왕복 교통비(항공권/KTX 등)를 추정한다. "
        "알려진 노선(서울-부산 KTX, 서울-강릉 KTX, 제주행 국내선 항공)만 추정치를 제공하고, "
        "모르는 노선은 정보 없음으로 정직하게 답한다 - 절대 임의로 금액을 지어내지 않는다. "
        "이 값은 calculate_budget_allocation과 별개이며, 예산 배분 전에 총 예산에서 미리 "
        "빼야 할 참고용 추정치다."
    ),
    args_schema=TransportInput,
)
def estimate_round_trip_transport(departure: str, destination: str, people: int) -> str:
    try:
        departure = departure.strip()
        destination = destination.strip()

        if destination == "제주":
            r = JEJU_FLIGHT_FARE_RANGE
            result = {
                "departure": departure,
                "destination": destination,
                "known": True,
                "수단": "국내선 항공 (제주는 항공편 외 왕복 대안이 사실상 없음)",
                "편도_1인_최저": r["편도_최저"],
                "편도_1인_평시": r["편도_평시"],
                "편도_1인_성수기": r["편도_성수기"],
                "왕복_추정_평시_전체인원": r["편도_평시"] * 2 * people,
                "note": (
                    "항공권은 예약 시점/시즌에 따라 변동이 크다. 평시 기준으로 추정했으며, "
                    "성수기(7월 중순~8월 말)에는 편도 15만원까지도 오를 수 있다. "
                    "정확한 금액은 항공사/여행 예약 사이트에서 직접 확인해야 한다."
                ),
            }
            return json.dumps(result, ensure_ascii=False)

        fare = FIXED_ROUTE_FARES.get((departure, destination))
        if fare is None:
            return json.dumps(
                {
                    "departure": departure,
                    "destination": destination,
                    "known": False,
                    "note": (
                        f"'{departure}'에서 '{destination}'까지의 교통비 정보가 없습니다. "
                        "임의로 금액을 추정하지 않으니, 사용자에게 별도로 확인이 필요하다고 "
                        "안내하고 이 금액 없이 현지 예산만 배분하세요."
                    ),
                },
                ensure_ascii=False,
            )

        result = {
            "departure": departure,
            "destination": destination,
            "known": True,
            "수단": fare["수단"],
            "편도_1인": fare["편도"],
            "왕복_추정_전체인원": fare["편도"] * 2 * people,
            "note": "코레일 공지 요금 기준 추정치이며, 실제 결제 시점 요금과 다를 수 있다.",
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"에러: 교통비 추정 중 문제가 발생했습니다 ({type(e).__name__}). 입력값을 확인 후 다시 시도하세요."
