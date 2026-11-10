"""Casevo adapter for configurable chat-completions and embeddings HTTP APIs.

No real service is contacted until API placeholders are replaced.
All retries live here; Casevo ThoughtChain retries are deliberately not layered on top.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
import time
from urllib.parse import urlparse

import httpx
from casevo import LLM_INTERFACE
from chromadb.api.types import EmbeddingFunction


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Command-wide budget, including baselines, embeddings and failed attempts."""
    def __init__(self, config, backend):
        self.limits = dict(config["budgets"])
        if backend == "real":
            self.limits["max_total_tokens"] = int(os.environ.get(
                "CASEVO_MAX_TOTAL_TOKENS", self.limits["max_total_tokens"]))
        self.started = time.monotonic()
        self.requests = self.text_requests = self.accounted_tokens = 0
        self.known_tokens = 0
        self.unknown_usage_requests = 0
        for field in ("max_requests", "max_text_requests", "max_seconds"):
            if self.limits[field] <= 0:
                raise ValueError(f"Budget {field} must be positive")
        token_limit = self.limits["max_total_tokens"]
        if type(token_limit) is not int or token_limit < 0:
            raise ValueError("CASEVO_MAX_TOTAL_TOKENS must be nonnegative; 0 means unlimited")

    def reserve(self, kind, estimate):
        if time.monotonic() - self.started >= self.limits["max_seconds"]:
            raise BudgetExceeded("Wall-time budget exhausted")
        if self.requests >= self.limits["max_requests"]:
            raise BudgetExceeded("Request budget exhausted")
        if kind == "text" and self.text_requests >= self.limits["max_text_requests"]:
            raise BudgetExceeded("Text request budget exhausted")
        limit = self.limits["max_total_tokens"]
        if limit > 0 and self.accounted_tokens + estimate > limit:
            raise BudgetExceeded("Token allowance insufficient for next estimated request")
        self.requests += 1
        self.text_requests += int(kind == "text")
        self.accounted_tokens += estimate

    def settle(self, estimate, usage):
        actual = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(actual) is int and actual >= 0:
            self.accounted_tokens += actual - estimate
            self.known_tokens += actual
        else:
            self.unknown_usage_requests += 1

    def report(self):
        return {"requests": self.requests, "text_requests": self.text_requests,
                "accounted_tokens": self.accounted_tokens, "reported_tokens": self.known_tokens,
                "unknown_usage_requests": self.unknown_usage_requests,
                "elapsed_seconds": round(time.monotonic() - self.started, 3), "limits": self.limits}


class RuntimeEmbedding(EmbeddingFunction):
    def __init__(self, adapter):
        self.adapter = adapter

    def __call__(self, input):
        return self.adapter.send_embedding(list(input))

    @staticmethod
    def name():
        return "casevo-clarification-runtime-v1"

    def get_config(self):
        return {"model": self.adapter.embedding_model}

    @staticmethod
    def build_from_config(config):
        # Runtime credentials, request budgets and logging must be explicitly rebound.
        # Tell Chroma this is a runtime (legacy) embedding, never silently recreate it.
        return NotImplemented


class BaseAdapter(LLM_INTERFACE):
    backend = "base"
    embedding_model = "runtime"

    def __init__(self, config, budget):
        self.config, self.budget = config, budget
        self.store = None
        self.context = {}
        self._embedding = RuntimeEmbedding(self)

    @contextmanager
    def scope(self, store, **context):
        previous = self.store, self.context
        self.store, self.context = store, context
        try:
            yield
        finally:
            self.store, self.context = previous

    def get_lang_embedding(self):
        return self._embedding

    def send_message(self, prompt, json_flag=False):
        def validate(text):
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Text response must be nonempty")
            return text
        return self.generate(prompt, validate, json_flag=json_flag)

    def generate(self, prompt, validator, json_flag=False):
        if len(prompt) > self.config["max_prompt_chars"]:
            raise ValueError("Prompt exceeds frozen size limit; no silent truncation")
        return self._request("text", prompt, validator, json_flag)

    def send_embedding(self, text_list):
        if not text_list:
            return []

        def validate(vectors):
            if len(vectors) != len(text_list):
                raise ValueError("Embedding count mismatch")
            size = len(vectors[0])
            if not size or any(len(v) != size or any(type(x) not in (float, int) or not math.isfinite(x) for x in v) for v in vectors):
                raise ValueError("Invalid embedding vectors")
            old = getattr(self, "embedding_dimension", size)
            if old != size:
                raise ValueError("Embedding dimension changed")
            self.embedding_dimension = size
            return vectors

        return self._request("embedding", text_list, validate)

    def _request(self, kind, payload, validator, json_flag=False):
        if self.store is None:
            raise RuntimeError("Adapter calls require an auditable run store")
        # Byte count + allowance is a conservative local estimate, not a provider tokenizer.
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        estimate = size + (self.config["max_output_tokens"] + 128 if kind == "text" else 0)
        for attempt in range(1, self.config["max_attempts"] + 1):
            self.budget.reserve(kind, estimate)
            request_id = f"request_{self.budget.requests:06d}"
            begin = time.monotonic()
            usage, response = {}, None
            record = {**self.context, "id": request_id, "kind": kind, "backend": self.backend,
                      "attempt": attempt, "estimated_token_allowance": estimate,
                      "status": "interrupted",
                      "input_text_count": len(payload) if kind == "embedding" else 1}
            if kind == "text":
                (self.store.path / "prompts" / (request_id + ".txt")).write_text(payload, encoding="utf-8")
            else:
                self.store.save("prompts/" + request_id + ".json", payload)
            try:
                output, response, usage = self._dispatch(kind, payload, json_flag)
                record["status"] = "success"
                result = validator(output)
            except Exception as error:
                record["status"] = "failed"
                # Do not print server bodies, request headers, keys or raw exception URLs.
                record["error_type"] = type(error).__name__
                fatal = isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in (408, 429, 500, 502, 503, 504)
                if isinstance(error, httpx.HTTPStatusError):
                    record["http_status"] = error.response.status_code
                retry = attempt < self.config["max_attempts"] and not fatal
            finally:
                self.budget.settle(estimate, usage)
                record["usage"] = usage or None
                record["elapsed_seconds"] = round(time.monotonic() - begin, 4)
                if response is not None:
                    self.store.save("responses/" + request_id + ".json", response)
                self.store.append("calls", record)
            if record["status"] == "success":
                return result
            if not retry:
                raise RuntimeError(f"{kind} request failed; see calls.jsonl ({record['error_type']})")
            time.sleep(min(0.2 * 2 ** (attempt - 1), 2))
        raise RuntimeError("Unreachable retry state")


class RealAdapter(BaseAdapter):
    backend = "real"

    def __init__(self, config, budget):
        super().__init__(config, budget)
        self.chat_url = os.environ.get("CASEVO_CHAT_BASE_URL", config["chat_base_url"]).rstrip("/")
        self.embedding_url = os.environ.get("CASEVO_EMBEDDING_BASE_URL", config["embedding_base_url"]).rstrip("/")
        self.chat_model = os.environ.get("CASEVO_CHAT_MODEL", config["chat_model"])
        self.embedding_model = os.environ.get("CASEVO_EMBEDDING_MODEL", config["embedding_model"])
        self.chat_key = os.environ.get("CASEVO_CHAT_API_KEY", "111111")
        self.embedding_key = os.environ.get("CASEVO_EMBEDDING_API_KEY", "111111")
        self.preflight()

    def preflight(self):
        for label, url, model, key in (("chat", self.chat_url, self.chat_model, self.chat_key),
                                       ("embedding", self.embedding_url, self.embedding_model, self.embedding_key)):
            parsed = urlparse(url)
            if not model or model == "aaa" or not key or key == "111111" or parsed.hostname in (None, "aaa", "aaa.invalid"):
                raise ValueError(f"Replace {label} API placeholders in .env/config.json first")
            if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(f"Invalid {label} base URL")

    def public_settings(self):
        return {"chat_base_url": self.chat_url, "chat_model": self.chat_model,
                "embedding_base_url": self.embedding_url, "embedding_model": self.embedding_model,
                "chat_key_configured": True, "embedding_key_configured": True}

    def _dispatch(self, kind, payload, json_flag):
        if kind == "text":
            body = {"model": self.chat_model, "messages": [{"role": "user", "content": payload}],
                    "max_tokens": self.config["max_output_tokens"]}
            if self.config["send_temperature"]:
                body["temperature"] = self.config["temperature"]
            if self.config.get("thinking_type") is not None:
                body["thinking"] = {"type": self.config["thinking_type"]}
            if self.config.get("reasoning_effort") is not None:
                body["reasoning_effort"] = self.config["reasoning_effort"]
            if self.config["send_seed"]:
                seed_text = str((self.config["seed"], self.context.get("repeat"), self.context.get("round"), self.context.get("node"), self.context.get("stage")))
                body["seed"] = int(hashlib.sha256(seed_text.encode()).hexdigest()[:7], 16)
            if json_flag and self.config["json_mode"]:
                body["response_format"] = {"type": "json_object"}
            url, key = self.chat_url + "/chat/completions", self.chat_key
        else:
            body = {"model": self.embedding_model, "input": payload}
            url, key = self.embedding_url + "/embeddings", self.embedding_key
        with httpx.Client(timeout=self.config["timeout_seconds"], follow_redirects=False) as client:
            res = client.post(url, headers={"Authorization": "Bearer " + key}, json=body)
            res.raise_for_status()
            data = res.json()
        if kind == "text":
            output = data["choices"][0]["message"]["content"]
        else:
            rows = sorted(data["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(payload))):
                raise ValueError("Embedding response indices mismatch")
            output = [row["embedding"] for row in rows]
        return output, data, data.get("usage") or {}
