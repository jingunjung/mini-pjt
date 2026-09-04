# rag_search_tool.py - 국내 관광지/맛집/숨은명소 RAG 검색 로직.
# reference/day2_practice/rag_chain.py, verify_sources.py, day6_practice/build_chroma.py 패턴을
# 그대로 따르되, 컬렉션/문서를 이번 프로젝트의 관광 데이터로 교체했다.
# 이 모듈의 search_travel_info()는 src/tools/mcp_server.py에서 MCP 도구로 노출된다
# (day4_practice/mcp_server.py 패턴).
import re
import sys
from functools import lru_cache
from pathlib import Path

from langchain_aws import BedrockEmbeddings
from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from pydantic import BaseModel, Field

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


def _simple_korean_tokenize(text: str) -> list[str]:
    """kiwipiepy 같은 형태소 분석기 없이 쓰는 가벼운 토크나이저.

    한글 음절 시퀀스와 영숫자 토큰만 남긴다 - 이 프로젝트 문서는 "이름 - 주소" 형태의 짧은
    고유명사 위주라 형태소 분석 없이도 BM25 키워드 매칭에 충분하다 (kiwipiepy 도입 시
    reference/day2_practice/hybrid.py의 korean_tokenizer로 교체하면 된다).
    """
    return re.findall(r"[가-힣]+|[A-Za-z0-9]+", text)


@lru_cache(maxsize=1)
def _get_bm25_retriever() -> BM25Retriever:
    collection = _get_vectorstore().get()
    documents = collection.get("documents") or []
    metadatas = collection.get("metadatas") or [{}] * len(documents)
    docs = [Document(page_content=c, metadata=m) for c, m in zip(documents, metadatas)]
    retriever = BM25Retriever.from_documents(docs, preprocess_func=_simple_korean_tokenize)
    retriever.k = 5
    return retriever


@lru_cache(maxsize=1)
def _get_hybrid_retriever() -> EnsembleRetriever:
    """BM25(키워드) + 벡터(의미) 하이브리드 검색기 (reference/day2_practice/hybrid.py 패턴).

    "제주 관광지" 같은 키워드형 질의는 BM25가, "혼자 조용히 쉴 수 있는 곳" 같은 의미형
    질의는 벡터 검색이 유리해서 두 결과를 가중합(EnsembleRetriever)한다.
    """
    return EnsembleRetriever(
        retrievers=[_get_bm25_retriever(), _get_retriever()],
        weights=[0.4, 0.6],
    )


class _ExpandedQueries(BaseModel):
    queries: list[str] = Field(
        description="원 질의를 포함해 검색 재현율을 높이기 위한 2~3개의 관련 검색 질의 목록"
    )


def expand_query(query: str) -> list[str]:
    """LLM으로 원 질의를 2~3개의 관련 질의로 확장한다 (쿼리 확장).

    사용자가 짧고 모호하게 물어도("제주 놀거리") 문서의 실제 표현("관광지", "체험마을" 등)과
    가까운 재질의를 함께 검색해 재현율을 높인다. 실패하면 원 질의 하나만 그대로 쓴다
    (fail-open - 확장 실패가 검색 자체를 막으면 안 된다).
    """
    from langchain_core.prompts import ChatPromptTemplate

    from config import make_chat_llm

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 국내 여행(제주/부산/강릉) 검색 질의 확장기다. 사용자 질의 하나를 받아서, "
                "같은 정보 요구를 다른 표현으로 담은 관련 검색 질의를 원래 질의 포함 2~3개 "
                "만들어라. 지역명·카테고리(관광지/맛집/숙소/숨은명소) 같은 문서에 실제 쓰이는 "
                "표현을 적극적으로 섞어라.",
            ),
            ("human", "{query}"),
        ]
    )
    chain = prompt | make_chat_llm(temperature=0).with_structured_output(_ExpandedQueries)
    try:
        result = chain.invoke({"query": query})
        queries = [q for q in (result.queries or []) if q and q.strip()]
    except Exception as e:
        print(f"[경고] 쿼리 확장 실패, 원 질의만 사용: {type(e).__name__}: {e}")
        queries = []
    if query not in queries:
        queries.insert(0, query)
    return queries[:3]


def hybrid_search_with_expansion(query: str, k: int = 5) -> list[Document]:
    """쿼리 확장 + 하이브리드(BM25+벡터) 검색을 결합해 컨텍스트 문서를 반환한다.

    RAG API(/query)의 retrieve 단계에서 쓰인다. 확장된 질의마다 하이브리드 검색을 돌리고,
    chunk_id 기준으로 중복 제거한 뒤 상위 k개를 반환한다.
    """
    retriever = _get_hybrid_retriever()
    seen: dict[str, Document] = {}
    for q in expand_query(query):
        for doc in retriever.invoke(q):
            doc_id = doc.metadata.get("chunk_id") or doc.metadata.get("source") or doc.page_content[:30]
            seen.setdefault(doc_id, doc)
    return list(seen.values())[:k]


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
