# file_tracer.py - 실행 기록을 JSONL로 남기는 간단한 콜백 핸들러.
# reference/day7_practice/local_tracer.py 그대로 재사용 (데모/디버깅용).
import json
import time
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler


class FileTracer(BaseCallbackHandler):
    def __init__(self, path: str = "travel_trace.jsonl"):
        self.path = Path(path)
        self._starts: dict[str, float] = {}

    def _write(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._starts[str(run_id)] = time.time()
        preview = ""
        try:
            preview = str(messages[-1][-1].content)[:200]
        except Exception:
            pass
        self._write({"event": "llm_start", "run_id": str(run_id), "input_preview": preview})

    def on_llm_end(self, response, *, run_id, **kwargs):
        latency = time.time() - self._starts.pop(str(run_id), time.time())
        text_preview = ""
        usage = None
        try:
            gen = response.generations[0][0]
            text_preview = str(getattr(gen, "text", ""))[:200]
            usage = getattr(gen.message, "usage_metadata", None)
        except Exception:
            pass
        self._write(
            {
                "event": "llm_end",
                "run_id": str(run_id),
                "latency_s": round(latency, 3),
                "output_preview": text_preview,
                "usage": usage,
            }
        )

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._write({"event": "llm_error", "run_id": str(run_id), "error": str(error)})

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._starts[str(run_id)] = time.time()
        self._write(
            {
                "event": "tool_start",
                "run_id": str(run_id),
                "tool": serialized.get("name", "unknown"),
                "input": str(input_str)[:200],
            }
        )

    def on_tool_end(self, output, *, run_id, **kwargs):
        latency = time.time() - self._starts.pop(str(run_id), time.time())
        self._write(
            {
                "event": "tool_end",
                "run_id": str(run_id),
                "latency_s": round(latency, 3),
                "output": str(output)[:200],
            }
        )
