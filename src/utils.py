# utils.py - 여러 모듈에서 공유하는 작은 헬퍼.
# reference/day6_practice, day7_practice 전 파일에 반복되는 get_text() 그대로.


def get_text(message) -> str:
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환한다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content
