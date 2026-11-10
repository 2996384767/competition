"""Deterministic mechanism fixture, NOT an empirical model of human behaviour."""
import hashlib
import json

from llm_adapter import BaseAdapter


class MockAdapter(BaseAdapter):
    backend = "mock"
    embedding_model = "mock-hash-16"

    def __init__(self, config, budget, share=True):
        super().__init__(config, budget)
        self.share = share

    def public_settings(self):
        return {"chat_model": "mock-fixed-rule", "embedding_model": self.embedding_model,
                "warning": "Synthetic mechanism checks only; no real API requests"}

    def _dispatch(self, kind, payload, json_flag):
        if kind == "embedding":
            vectors = []
            for text in payload:
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                vectors.append([(b - 127.5) / 127.5 for b in digest[:16]])
            return vectors, {"mock": True, "vectors": vectors}, {}
        visible = json.loads(payload.split("<<<CONTEXT>>>\n", 1)[1].split("\n<<<END>>>", 1)[0])
        text = json.dumps(visible, ensure_ascii=False)
        corrected = "价格保持不变" in text
        if visible["task"] == "reflect":
            output = ("收到关于营业时间调整、打印价格保持不变的说法，需保留来源并区分传闻。" if corrected
                      else "只接触到可能涨价的传闻，尚未见到明确公告，需要核实。")
        else:
            output = json.dumps({
                "belief_price_increase": 0.1 if corrected else 0.7,
                "opinion": "收到价格保持不变的说法。" if corrected else "尚未核实涨价传闻。",
                "message": ("转述所收到的信息：下周仅调整营业时间，打印价格保持不变。" if corrected
                            else "听说下周可能涨价，有人能核实吗？"),
                "share": self.share,
            }, ensure_ascii=False)
        return output, {"mock": True, "content": output}, {}
