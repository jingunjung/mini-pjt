# rag_search_tool.py - 국내 관광지/맛집/숨은명소 RAG 검색 로직.
# reference/day2_practice/rag_chain.py, verify_sources.py, day6_practice/build_chroma.py 패턴을
# 그대로 따르되, 컬렉션/문서를 이번 프로젝트의 관광 데이터로 교체했다.
# 이 모듈의 search_travel_info()는 src/tools/mcp_server.py에서 MCP 도구로 노출된다
# (day4_practice/mcp_server.py 패턴).
import sys
from functools import lru_cache
from pathlib import Path

from langchain_aws import BedrockEmbeddings
from langchain_chroma import Chroma

# 이 파일이 어떤 cwd에서 실행/임포트되든 src/ 를 찾을 수 있도록 경로를 보정한다
# (MCP 서버로 별도 프로세스 실행될 때 특히 필요 - day4_practice/mcp_agent.py의
#  "SERVER_PATH를 __file__ 기준 절대경로로 잡는다" 패턴과 같은 이유).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CHROMA_COLLECTION, CHROMA_DIR, EMBEDDING_MODEL_ID, REGION  # noqa: E402


@lru_cache(maxsize=1)
def _get_vectorstore():
    embeddings = BedrockEmbeddings(model_id=EMBEDDING_MODEL_ID, region_name=REGION)
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        collection_name=CHROMA_COLLECTION,
    )


@lru_cache(maxsize=1)
def _get_retriever():
    # 폴백 문서 시절(지역당 10여 항목)보다 실제 TourAPI 데이터(지역당 60항목, ~45개 청크)가
    # 훨씬 커져서, k=3이면 관광지/맛집/숙소 세 카테고리를 한 번에 다루기엔 부족하다.
    return _get_vectorstore().as_retriever(search_kwargs={"k": 5})


def search_travel_info(query: str) -> str:
    """국내 관광지/맛집/숙소/숨은명소 문서에서 질의와 관련된 내용을 검색해 근거와 함께 반환한다.

    반드시 이 검색 결과에 근거해서만 장소를 추천하고, 문서에 없는 장소는 지어내지 않는다.
    """
    retriever = _get_retriever()
    docs = retriever.invoke(query)
    if not docs:
        return "관련 여행 정보를 찾지 못했습니다."
    return "\n\n".join(
        f"[출처: {d.metadata.get('source', '알 수 없음')} / 지역: {d.metadata.get('region', '알 수 없음')}]\n{d.page_content}"
        for d in docs
    )


def get_grounding_sources(query: str) -> list[dict]:  # noqa: ARG001 - query는 인터페이스 호환용으로 남겨둠
    """가드레일(그라운딩 체크)이 재사용하는 헬퍼: 전체 문서 코퍼스를 원문 그대로 반환한다.

    day2_practice/verify_sources.py 의 RunnableParallel(answer=..., sources=...) 패턴과 같은 목적으로,
    답변에 등장한 장소명이 실제로 문서 안에 있는지 문자열 매칭하는 데 사용한다.

    검색 도구(search_travel_info)는 질의와 유사한 상위 k=3 청크만 반환하지만, 그라운딩 체크는
    "Supervisor가 여러 하위 질의로 나눠 검색한 결과를 종합해 만든 최종 답변"을 검증하는 것이라
    원본 query 하나로 top-k만 다시 검색하면 실제로 근거가 있는 장소도 빠뜨려 오탐(false
    positive)이 나기 쉽다. 이 프로젝트의 코퍼스는 3개 지역 문서·10개 청크로 작아서, 유사도
    검색 대신 전체 컬렉션을 그대로 가져와 비교하는 편이 더 정확하다 (코퍼스가 커지면 대표
    키워드별로 여러 번 검색해 합치는 방식으로 바꿔야 한다).
    """
    collection = _get_vectorstore().get()
    documents = collection.get("documents") or []
    metadatas = collection.get("metadatas") or [{}] * len(documents)
    return [
        {
            "source": meta.get("source", "알 수 없음"),
            "region": meta.get("region", "알 수 없음"),
            "content": content,
        }
        for content, meta in zip(documents, metadatas)
    ]
