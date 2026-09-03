# run_eval.py - evaluation/test_queries.csv 를 실제 시스템에 돌려 자동 채점한다.
# HITL interrupt가 있는 outer_graph 대신 Supervisor를 직접 ainvoke한다 (배치 평가는 사람의
# 승인 개입 없이 끝까지 자동 실행돼야 하므로). day7_practice/run_eval.py의 ToolRecorder 콜백과
# input_guard를 미리 적용하는 패턴은 그대로 가져오되, 스키마는 test_queries.csv 기준으로 새로 짰다.
import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from agents.supervisor import build_supervisor  # noqa: E402
from config import RECURSION_LIMIT  # noqa: E402
from graph.guardrails import input_guard, refusal_message  # noqa: E402
from llm_judge import judge_answer  # noqa: E402
from utils import get_text  # noqa: E402

CSV_PATH = Path(__file__).resolve().parent / "test_queries.csv"
RESULT_PATH = Path(__file__).resolve().parent / "eval_result.json"
# 평가 산출물 요건: 사람이 바로 읽을 수 있는 마크다운 리포트를 evaluation/round1_report.md로 남긴다.
# eval_result.json은 케이스별 원본 데이터(디버깅/재분석용)로 계속 같이 남기고, 이 리포트는 그
# 데이터를 요약·정리한 제출용 산출물이다.
REPORT_PATH = Path(__file__).resolve().parent / "round1_report.md"
PASS_THRESHOLD = 0.8


class ToolRecorder(BaseCallbackHandler):
    """Supervisor 서브 에이전트가 호출한 도구 이름을 기록한다 (day7 run_eval.py의 ToolRecorder)."""

    def __init__(self):
        self.tools_called: list[str] = []

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tools_called.append(serialized.get("name", "unknown"))


def _split(field: str) -> list[str]:
    return [item.strip() for item in field.split(";") if item.strip()]


def load_cases() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


async def run_case(supervisor, case: dict) -> dict:
    expected_traits = _split(case["expected_traits"])
    forbidden = _split(case["forbidden"])
    expected_tools = _split(case["expected_tools"])

    blocked, guard_reason = input_guard(case["input"])
    if blocked:
        answer = refusal_message(guard_reason)
        tools_called: list[str] = []
    else:
        recorder = ToolRecorder()
        result = await supervisor.ainvoke(
            {"messages": [HumanMessage(content=case["input"])]},
            config={"recursion_limit": RECURSION_LIMIT, "callbacks": [recorder]},
        )
        answer = get_text(result["messages"][-1])
        tools_called = recorder.tools_called

    judged = judge_answer(answer, expected_traits, forbidden)
    tools_ok = all(t in tools_called for t in expected_tools) if expected_tools else True
    passed = judged.passed and tools_ok

    return {
        "id": case["id"],
        "category": case["category"],
        "input": case["input"],
        "passed": passed,
        "missing_traits": judged.missing_traits,
        "violated_forbidden": judged.violated_forbidden,
        "expected_tools": expected_tools,
        "tools_called": tools_called,
        "tools_ok": tools_ok,
        "answer_preview": answer[:300],
        "note": case.get("note", ""),
    }


def write_markdown_report(
    results: list[dict], by_category: dict[str, list[bool]], pass_rate: float, verdict: str
) -> None:
    """케이스별 상세 JSON과 별도로, 제출/공유용 사람이 읽는 요약 리포트를 마크다운으로 남긴다."""
    total = len(results)
    passed = sum(r["passed"] for r in results)
    lines = [
        "# 평가 결과 리포트 (Round 1)",
        "",
        f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 평가셋: `test_queries.csv` ({total}건)",
        f"- 전체 통과율: **{passed}/{total} ({pass_rate:.0%})**",
        f"- DoD 판정 ({PASS_THRESHOLD:.0%} 이상 통과 기준): **{verdict}**",
        "",
        "## 카테고리별 결과",
        "",
        "| 카테고리 | 통과 | 전체 | 비율 |",
        "|---|---|---|---|",
    ]
    for cat, vals in sorted(by_category.items()):
        lines.append(f"| {cat} | {sum(vals)} | {len(vals)} | {sum(vals) / len(vals):.0%} |")

    lines += [
        "",
        "## 케이스별 결과",
        "",
        "| ID | 카테고리 | 결과 | 입력 |",
        "|---|---|---|---|",
    ]
    for r in results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        input_preview = r["input"].replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['category']} | {status} | {input_preview} |")

    failed = [r for r in results if not r["passed"]]
    if failed:
        lines += ["", "## 실패 케이스 상세", ""]
        for r in failed:
            lines.append(f"### ID {r['id']} ({r['category']}) - {r['input']}")
            lines.append("")
            if r.get("error"):
                lines.append(f"- 실행 오류: `{r['error']}`")
            if r["missing_traits"]:
                lines.append(f"- 누락된 expected_traits: {r['missing_traits']}")
            if r["violated_forbidden"]:
                lines.append(f"- 위반된 forbidden: {r['violated_forbidden']}")
            if not r["tools_ok"]:
                lines.append(f"- 기대 도구: {r['expected_tools']}")
                lines.append(f"- 실제 호출된 도구: {r['tools_called']}")
            if r.get("answer_preview"):
                lines.append(f"- 답변 미리보기: {r['answer_preview']}")
            lines.append("")
    else:
        lines += ["", "## 실패 케이스 상세", "", "실패한 케이스 없음.", ""]

    lines.append(f"> 케이스별 원본 데이터(도구 호출 기록 등)는 `{RESULT_PATH.name}` 참고.")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    cases = load_cases()

    results = []
    for case in cases:
        try:
            # 케이스마다 Supervisor를 새로 지어서 make_chat_llm()의 모델 라운드로빈이 실제로
            # 케이스마다 다음 모델로 넘어가게 한다 - 한 번 지어서 20건 내내 재사용하면 라운드
            # 로빈 목록의 처음 4개 모델에만 부하가 몰려 스로틀링 회피 효과가 없다.
            supervisor = await build_supervisor()
            r = await run_case(supervisor, case)
        except Exception as e:
            # 한 케이스의 일시적 오류(예: Bedrock 타임아웃)로 전체 배치가 죽지 않도록,
            # 실패로 기록만 하고 다음 케이스로 계속 진행한다.
            r = {
                "id": case["id"], "category": case["category"], "input": case["input"],
                "passed": False, "missing_traits": [], "violated_forbidden": [],
                "expected_tools": _split(case["expected_tools"]), "tools_called": [],
                "tools_ok": False, "answer_preview": "", "note": case.get("note", ""),
                "error": f"{type(e).__name__}: {e}",
            }
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{r['id']:>2}][{r['category']:<10}] {status}  {r['input'][:40]}")
        if r.get("error"):
            print(f"      - 실행 오류: {r['error']}")
        if not r["passed"]:
            if r["missing_traits"]:
                print(f"      - 누락된 expected_traits: {r['missing_traits']}")
            if r["violated_forbidden"]:
                print(f"      - 위반된 forbidden: {r['violated_forbidden']}")
            if not r["tools_ok"]:
                print(f"      - 기대 도구 미호출: 기대={r['expected_tools']} 실제={r['tools_called']}")

    total = len(results)
    passed = sum(r["passed"] for r in results)
    pass_rate = passed / total if total else 0.0

    by_category: dict[str, list[bool]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r["passed"])

    print(f"\n전체: {passed}/{total} ({pass_rate:.0%})")
    for cat, vals in sorted(by_category.items()):
        print(f"  {cat}: {sum(vals)}/{len(vals)} ({sum(vals) / len(vals):.0%})")

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n상세 결과 저장: {RESULT_PATH}")

    verdict = "PASS" if pass_rate >= PASS_THRESHOLD else "FAIL"
    print(f"\nDoD 판정 ({PASS_THRESHOLD:.0%} 이상 통과 기준): {verdict}")

    write_markdown_report(results, by_category, pass_rate, verdict)
    print(f"리포트 저장: {REPORT_PATH}")

    sys.exit(0 if pass_rate >= PASS_THRESHOLD else 1)


if __name__ == "__main__":
    asyncio.run(main())
