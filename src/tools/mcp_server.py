# mcp_server.py - 국내 관광 RAG 검색을 MCP 도구로 노출하는 서버.
# reference/day4_practice/mcp_server.py 패턴 그대로: FastMCP + @mcp.tool(), stdio 모드로 대기.
# 단, FastMCP는 별도 fastmcp 패키지가 아니라 mcp SDK에 내장된 mcp.server.fastmcp.FastMCP를
# 쓴다 (langchain-mcp-adapters와의 mcp 버전 호환 문제, requirements.txt 주석 참고).
#
# 실행: python src/tools/mcp_server.py  (보통은 MultiServerMCPClient가 서브프로세스로 실행함)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp.server.fastmcp import FastMCP  # noqa: E402

from tools.rag_search_tool import search_travel_info  # noqa: E402

mcp = FastMCP("travel-planner-data")


@mcp.tool()
def search_destination_info(query: str) -> str:
    """국내 관광지/맛집/숙소/숨은명소 정보를 검색한다.

    지역, 여행지, 맛집, 숙소(호텔/게스트하우스/펜션), 숨은 명소에 대한 질문에 사용한다.
    예산 계산이나 일정 검증에는 사용하지 않는다 (calculate_budget_allocation,
    validate_itinerary 사용).

    Args:
        query: 검색하고 싶은 지역/장소/취향 관련 질의 (예: "제주 숨은 맛집", "부산 숙소")
    """
    return search_travel_info(query)


if __name__ == "__main__":
    mcp.run()  # stdio 모드
