# build_chroma.py - data/docs/*.md 를 임베딩해 Chroma 벡터DB(data/chroma_travel/)를 생성한다.
# reference/day6_practice/build_chroma.py 패턴을 그대로 따르되, HR 정책 문서 대신 관광 데이터를
# 쓰므로 collection_name/persist_directory를 이 프로젝트 전용 값으로 새로 잡는다.
#
# 실행: python data/build_chroma.py
import sys
from pathlib import Path

from langchain_aws import BedrockEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config import CHROMA_COLLECTION, CHROMA_DIR, DOCS_DIR, EMBEDDING_MODEL_ID, REGION  # noqa: E402

# 문서별 메타데이터 (지역명) - RAG 검색 결과의 출처 표기와 가드레일의 지역 정합성 체크에 쓰인다.
FILE_META = {
    "제주.md": {"region": "제주"},
    "부산.md": {"region": "부산"},
    "강릉.md": {"region": "강릉"},
}


def load_chunks():
    splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    chunks = []
    for filename, meta in FILE_META.items():
        path = DOCS_DIR / filename
        if not path.exists():
            print(f"[경고] {path} 없음 - 건너뜀")
            continue
        docs = TextLoader(str(path), encoding="utf-8").load()
        for d in docs:
            d.metadata.update(meta)
            d.metadata["source"] = filename
        file_chunks = splitter.split_documents(docs)
        # chunk_id: RAG API 응답의 contexts[].doc_id로 그대로 쓰인다 - 파일명#순번 형태의
        # 안정적인 식별자를 미리 메타데이터에 박아둔다 (Chroma 내부 uuid는 재빌드마다 바뀜).
        for i, c in enumerate(file_chunks):
            c.metadata["chunk_id"] = f"{filename}#{i}"
        chunks.extend(file_chunks)
    return chunks


def main():
    chunks = load_chunks()
    if not chunks:
        print("생성할 청크가 없습니다. data/docs/ 에 문서를 준비하세요.")
        return

    embeddings = BedrockEmbeddings(model_id=EMBEDDING_MODEL_ID, region_name=REGION)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=CHROMA_COLLECTION,
        persist_directory=str(CHROMA_DIR),
    )
    print(f"생성 완료: {len(chunks)}개 청크 -> {CHROMA_DIR} (collection={CHROMA_COLLECTION})")


if __name__ == "__main__":
    main()
