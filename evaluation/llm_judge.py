# llm_judge.py - test_queries.csv의 expected_traits/forbidden 충족 여부를 LLM으로 심사한다.
# reference/day7_practice/llm_judge.py의 "고정 rubric + 구조화 출력" 패턴을 그대로 따르되,
# 정답(reference) 대조가 아니라 이 프로젝트의 CSV 스키마(expected_traits/forbidden)에 맞게
# rubric을 재작성했다.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ast  # noqa: E402

from pydantic import BaseModel, Field, field_validator  # noqa: E402

from config import make_chat_llm  # noqa: E402

_judge_llm = make_chat_llm(temperature=0)

RUBRIC = """다음 답변을 아래 기준으로 평가하세요. 표현 방식이나 문장 구조가 달라도 의미상
충족하면 통과로 판단하세요. 없는 사실을 답변이 실제로 포함하고 있는지만 보고, 표현의 길이나
문체는 평가하지 마세요.

- expected_traits: 목록에 있는 각 항목이 답변에서 실제로 확인되어야 통과입니다.
  하나라도 확인되지 않으면 missing_traits에 그 항목을 그대로 적으세요.
- forbidden: 목록에 있는 각 항목이 답변에 등장하면 안 됩니다.
  하나라도 등장하면 violated_forbidden에 그 항목을 그대로 적으세요.
- missing_traits와 violated_forbidden이 모두 비어 있어야 passed=true 입니다."""


class JudgeResult(BaseModel):
    passed: bool = Field(description="expected_traits를 모두 만족하고 forbidden을 하나도 위반하지 않으면 true")
    missing_traits: list[str] = Field(default_factory=list, description="충족되지 않은 expected_traits 항목")
    violated_forbidden: list[str] = Field(default_factory=list, description="답변에 등장한 forbidden 항목")
    reasoning: str = Field(description="판단 이유 한두 문장")

    # 심사 모델이 가끔 빈 문자열("")이나 파이썬 리스트를 흉내낸 문자열("['a', 'b']")을 반환해
    # 원래 스키마(list[str])로 바로 파싱하면 ValidationError로 배치 평가 전체가 죽는다.
    # 실제로 Sonnet(빈 문자열)과 Haiku(문자열화된 리스트) 양쪽에서 관측된 문제라 방어적으로
    # 보정한다 - 문자열이면 빈 값은 [], 리스트처럼 생겼으면 파싱, 그 외엔 단일 항목으로 감싼다.
    @field_validator("missing_traits", "violated_forbidden", mode="before")
    @classmethod
    def _coerce_to_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("[") and value.endswith("]"):
                try:
                    parsed = ast.literal_eval(value)
                    if isinstance(parsed, list):
                        return [str(x) for x in parsed]
                except (ValueError, SyntaxError):
                    pass
            return [value]
        return value


def judge_answer(answer: str, expected_traits: list[str], forbidden: list[str]) -> JudgeResult:
    judge = _judge_llm.with_structured_output(JudgeResult)
    prompt = (
        f"{RUBRIC}\n\n"
        f"[답변]\n{answer}\n\n"
        f"[expected_traits]\n{expected_traits}\n\n"
        f"[forbidden]\n{forbidden}"
    )
    return judge.invoke(prompt)
