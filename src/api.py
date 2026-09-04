# api.py - 표준 RAG QA API (과제 산출물 규약: POST /query).
# CLI(main.py)의 멀티에이전트 여행 계획 플로우와는 별개로, 이 API는 관광 데이터 문서에 대한
# "질문 -> 근거 기반 답변" 단일 RAG 질의응답을 표준 계약(answer/contexts/trace)으로 노출한다.
# LCEL 체인(Pydantic 구조화 출력, Day1) + 하이브리드 검색·쿼리 확장(RAG, Day2) + 요청별 트레이스
# 기록(Observability, Day7)을 한 엔드포인트에서 함께 보여준다.
#
# 실행: python src/api.py  (또는 uvicorn api:app --reload --app-dir src)
# 테스트: curl -X POST http://localhost:8000/query -H "Content-Type: application/json" \
#         -d '{"question": "제주 맛집 추천해줘"}'
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from config import make_chat_llm  # noqa: E402
from graph.guardrails import input_guard, refusal_message  # noqa: E402
from tools.rag_search_tool import expand_query, hybrid_search_with_expansion  # noqa: E402

app = FastAPI(
    title="국내 여행 플래너 RAG API",
    description="제주/부산/강릉 관광 데이터에 대한 근거 기반 질의응답 API",
)


class QueryRequest(BaseModel):
    question: str = Field(description="사용자 질의")


# LCEL 체인의 최종 출력 스키마 (Pydantic 구조화 출력) - day1_practice/structured_output.py 패턴.
class RagAnswer(BaseModel):
    answer: str = Field(
        description="검색된 문서 내용에만 근거한 답변. 근거가 없으면 '문서에서 확인되지 않습니다'라고 답한다."
    )


ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "너는 국내 여행(제주/부산/강릉) 정보 안내 어시스턴트다. 아래 검색된 문서 내용에만 "
            "근거해 답하고, 문서에 없는 내용은 반드시 '문서에서 확인되지 않습니다'라고 답해라. "
            "장소명이나 주소를 절대 지어내지 마라.\n\n--- 검색된 문서 ---\n{context}",
        ),
        ("human", "{question}"),
    ]
)


def _format_context(docs: list[Document]) -> str:
    if not docs:
        return "관련 문서를 찾지 못했습니다."
    return "\n\n".join(f"[{d.metadata.get('chunk_id', d.metadata.get('source', '?'))}] {d.page_content}" for d in docs)


def _doc_id(d: Document) -> str:
    return d.metadata.get("chunk_id") or d.metadata.get("source") or "알 수 없음"


@app.post("/query")
def query(req: QueryRequest) -> dict:
    """근거 기반 RAG 질의응답. 응답 계약: {answer, contexts[], trace[]}."""
    trace: list[dict] = []

    t0 = time.time()
    blocked, reason = input_guard(req.question)
    trace.append(
        {
            "step": "guardrail",
            "input": req.question,
            "output": {"blocked": blocked, "reason": reason or None},
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }
    )
    if blocked:
        return {"answer": refusal_message(reason), "contexts": [], "trace": trace}

    t0 = time.time()
    expanded_queries = expand_query(req.question)
    trace.append(
        {
            "step": "query_expansion",
            "input": req.question,
            "output": expanded_queries,
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }
    )

    t0 = time.time()
    docs = hybrid_search_with_expansion(req.question)
    trace.append(
        {
            "step": "retrieve",
            "input": expanded_queries,
            "output": [_doc_id(d) for d in docs],
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }
    )

    t0 = time.time()
    context_text = _format_context(docs)
    chain = ANSWER_PROMPT | make_chat_llm(temperature=0).with_structured_output(RagAnswer)
    result: RagAnswer = chain.invoke({"context": context_text, "question": req.question})
    trace.append(
        {
            "step": "generate",
            "input": context_text[:300],
            "output": result.answer[:300],
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }
    )

    contexts = [{"doc_id": _doc_id(d), "text": d.page_content} for d in docs]
    return {"answer": result.answer, "contexts": contexts, "trace": trace}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
