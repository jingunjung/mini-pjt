# config.py - 프로젝트 전역 공용 설정
# reference/day2_practice, day6_practice, day7_practice 전 파일이 쓰는 값과 동일하게 맞춘다.
import itertools
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent  # mini-pjt/
load_dotenv(ROOT_DIR / ".env")

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# make_chat_llm()을 호출할 때마다 이 목록을 순서대로 돌려쓴다(itertools.cycle) - 여러 모델을
# 등록해두면 한 모델의 일일/분당 토큰 한도에 몰려 ThrottlingException이 나는 걸 분산시킬 수
# 있다. 지금은 global.anthropic.claude-sonnet-4-6 단일 모델만 쓰도록 고정했다 - 로테이션이
# 다시 필요하면 이 리스트에 모델 ID를 더 추가하면 된다.
CHAT_MODEL_IDS = [
    "global.anthropic.claude-sonnet-4-6",
]

DATA_DIR = ROOT_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"
CHROMA_DIR = DATA_DIR / "chroma_travel"
CHROMA_COLLECTION = "travel_spots"

MCP_SERVER_PATH = str((Path(__file__).resolve().parent / "tools" / "mcp_server.py"))

RECURSION_LIMIT = 30
CHECKPOINT_DB_PATH = str(ROOT_DIR / "checkpoints.sqlite")
STORE_DB_PATH = str(ROOT_DIR / "store.sqlite")
TRACE_LOG_PATH = str(ROOT_DIR / "travel_trace.jsonl")

TASTE_TAGS = ["맛집중심", "숨은여행지", "액티비티중심", "편안한숙소"]

# ChatBedrockConverse 기본 read/connect timeout(60초)이 Supervisor처럼 tool 호출이 여러 번
# 겹치는 호출에서는 종종 부족해 ReadTimeoutError가 난다. 모델 자체가 가끔 느리게 응답할 때도
# 있어(관측됨) timeout을 넉넉히 주는 것과 별개로 botocore 자동 재시도(max_retries)도 켜둔다.
# 모든 채팅 LLM을 이 팩토리로 통일해서 일괄 적용한다 (개별 파일에서 ChatBedrockConverse를
# 직접 생성하지 않는다).
CHAT_TIMEOUT_SECONDS = 180
CHAT_MAX_RETRIES = 3

_model_cycle = itertools.cycle(CHAT_MODEL_IDS)


def make_chat_llm(temperature: float = 0):
    from langchain_aws import ChatBedrockConverse

    model_id = next(_model_cycle)
    print(f"[모델] {model_id}")
    return ChatBedrockConverse(
        model=model_id,
        region_name=REGION,
        temperature=temperature,
        timeout=CHAT_TIMEOUT_SECONDS,
        max_retries=CHAT_MAX_RETRIES,
    )
