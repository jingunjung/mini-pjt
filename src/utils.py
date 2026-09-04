# utils.py - 여러 모듈에서 공유하는 작은 헬퍼.
# reference/day6_practice, day7_practice 전 파일에 반복되는 get_text() 그대로.


def get_text(message) -> str:
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환한다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


def get_final_answer(messages: list) -> str:
    """대화의 마지막 '실제 텍스트가 있는' 메시지를 반환한다.

    langgraph_supervisor는 각 Agent가 답한 뒤 Supervisor가 마지막에 한 번 더 종합
    메시지를 내는데, 좁은 범위(단일 Agent) 요청에서는 이 마지막 메시지의 content가
    완전히 빈 리스트(`[]`)로 오는 경우가 실제로 관측된다(핸드오프 뒤 더 보탤 말이
    없다고 판단하는 것으로 보임) - 이때 단순히 messages[-1]만 보면 사용자에게 빈
    답변이 그대로 노출된다. 뒤에서부터 텍스트가 있는 메시지를 찾아 그걸 최종 답변으로
    쓴다 (보통 곧바로 앞의, 전문 Agent 자신의 답변 메시지가 된다).
    """
    for message in reversed(messages):
        text = get_text(message)
        if text and text.strip():
            return text
    return ""
