"""Meaningful mechanism checks; all API traffic is mocked in-process."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from common import Store, load_inputs, read_json, validate_decision, write_json
from llm_adapter import Budget, BudgetExceeded, RealAdapter
from mock_llm import MockAdapter
from model import ClarificationModel
from run import execute, parser
from analyze import analyze, rows, verify_unit


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config, self.personas, self.materials = load_inputs()

    def tearDown(self):
        self.temp.cleanup()

    def model(self, name, condition="C", share=True, order=None):
        store = Store(self.root / name)
        adapter = MockAdapter(self.config, Budget(self.config, "mock"), share=share)
        model = ClarificationModel(self.config, self.personas, self.materials,
                                   self.personas["mappings"][0], adapter, store, condition=condition, order=order)
        return model, adapter, store

    def baseline(self):
        return {str(n): {"belief_price_increase": .7, "opinion": "尚待核实", "message": "有涨价传闻", "share": True} for n in range(1, 7)}

    def complete(self, model):
        model.initialize(self.baseline())
        for _ in range(3):
            model.step()

    def test_synchronous_inboxes_do_not_depend_on_execution_order(self):
        first, _, _ = self.model("first")
        second, _, _ = self.model("reverse", order=[6, 5, 4, 3, 2, 1])
        first.initialize(self.baseline())
        second.initialize(self.baseline())
        for t in range(1, 4):
            a, b = first.freeze_inboxes(t), second.freeze_inboxes(t)
            for n in a:
                self.assertEqual(sorted(a[n], key=lambda x: x["id"]), sorted(b[n], key=lambda x: x["id"]))
            first.step()
            second.step()

    def test_no_share_means_no_delivery_and_no_cross_node_leak(self):
        model, _, store = self.model("no_share", share=False)
        self.complete(model)
        self.assertEqual(rows(store.path / "deliveries.jsonl"), [])
        for node, agent in model.nodes.items():
            self.assertEqual(agent.state["belief_price_increase"], .1 if node == 3 else .7)

    def test_memory_is_in_next_prompt_and_only_visible_to_owner(self):
        model, _, store = self.model("memory")
        self.complete(model)
        calls = rows(store.path / "calls.jsonl")
        call = next(c for c in calls if c["kind"] == "text" and c["stage"] == "decision" and c["round"] == 2 and c["node"] == 4)
        text = (store.path / "prompts" / (call["id"] + ".txt")).read_text()
        payload = json.loads(text.split("<<<CONTEXT>>>\n")[1].split("\n<<<END>>>")[0])
        prior = next(s for s in rows(store.path / "states.jsonl") if s["round"] == 1 and s["node"] == 4)
        self.assertEqual(payload["long_memory"], prior["long_memory"])
        for memory in payload["relevant_memories"]:
            self.assertIn("agent_4", (memory["metadata"]["source"], memory["metadata"]["target"]))
        # The material is visible at t=0 to node 3 only.
        for c in calls:
            if c["kind"] == "text" and c["stage"] == "initialize":
                p = (store.path / "prompts" / (c["id"] + ".txt")).read_text()
                self.assertEqual("价格保持不变" in p, c["node"] == 3)

    def test_json_rejects_bad_types_and_bounds(self):
        valid = self.baseline()["1"]
        for key, value in [("belief_price_increase", True), ("belief_price_increase", 1.1), ("belief_price_increase", float("nan")), ("share", "false")]:
            bad = {**valid, key: value}
            with self.assertRaises(ValueError):
                validate_decision(json.dumps(bad))

    def test_retry_failure_is_logged_and_not_filled_with_defaults(self):
        model, adapter, store = self.model("retry")
        with patch.object(adapter, "_dispatch", return_value=("bad json", {"content": "bad json"}, {})), patch("llm_adapter.time.sleep"):
            with adapter.scope(store, stage="bad_output"):
                with self.assertRaises(RuntimeError):
                    adapter.generate("test", validate_decision)
        calls = rows(store.path / "calls.jsonl")
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c["status"] == "failed" for c in calls))
        self.assertIsNone(model.nodes[1].state)

    def test_request_budget_stops_before_next_request(self):
        _, adapter, store = self.model("budget")
        adapter.budget.limits["max_requests"] = 1
        with adapter.scope(store, stage="budget"):
            adapter.send_embedding(["one"])
            with self.assertRaises(BudgetExceeded):
                adapter.send_embedding(["two"])
        self.assertEqual(len(rows(store.path / "calls.jsonl")), 1)

    def test_real_token_budget_zero_is_unlimited_and_positive_still_enforced(self):
        with patch.dict("os.environ", {"CASEVO_MAX_TOTAL_TOKENS": "0"}, clear=True):
            budget = Budget(self.config, "real")
            budget.reserve("text", 10_000_000)
            budget.reserve("text", 10_000_000)
            self.assertEqual(budget.accounted_tokens, 20_000_000)
            # Unlimited tokens do not disable the independent request limit.
            budget.limits["max_requests"] = 2
            with self.assertRaises(BudgetExceeded):
                budget.reserve("text", 1)
        with patch.dict("os.environ", {"CASEVO_MAX_TOTAL_TOKENS": "100"}, clear=True):
            budget = Budget(self.config, "real")
            budget.reserve("text", 60)
            with self.assertRaises(BudgetExceeded):
                budget.reserve("text", 41)
        with patch.dict("os.environ", {"CASEVO_MAX_TOTAL_TOKENS": "-1"}, clear=True):
            with self.assertRaises(ValueError):
                Budget(self.config, "real")

    def test_real_placeholder_configuration_never_contacts_network(self):
        config = copy.deepcopy(self.config)
        config["budgets"]["max_total_tokens"] = 10000
        with patch.dict("os.environ", {}, clear=True), patch("llm_adapter.httpx.Client") as client:
            with self.assertRaises(ValueError):
                RealAdapter(config, Budget(config, "real"))
            client.assert_not_called()

    def test_real_adapter_request_shape_and_secret_free_logs(self):
        config = copy.deepcopy(self.config)
        config.update(chat_base_url="https://unit.test/v1", embedding_base_url="https://unit.test/v1",
                      chat_model="unit-chat", embedding_model="unit-embedding")
        config["budgets"]["max_total_tokens"] = 10000
        captured = []
        def handler(request):
            captured.append((request.url.path, json.loads(request.content)))
            if request.url.path.endswith("chat/completions"):
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(self.baseline()["1"])}}], "usage": {"total_tokens": 12}})
            return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0., 1.]}, {"index": 0, "embedding": [1., 0.]}], "usage": {"total_tokens": 3}})
        store = Store(self.root / "http")
        client_class = httpx.Client
        with patch.dict("os.environ", {"CASEVO_CHAT_API_KEY": "unit-secret", "CASEVO_EMBEDDING_API_KEY": "unit-secret"}, clear=True):
            adapter = RealAdapter(config, Budget(config, "real"))
            with patch("llm_adapter.httpx.Client", side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handler), **kw)):
                with adapter.scope(store, stage="http"):
                    adapter.generate("test", validate_decision)
                    self.assertEqual(adapter.send_embedding(["a", "b"]), [[1., 0.], [0., 1.]])
        self.assertEqual([p for p, _ in captured], ["/v1/chat/completions", "/v1/embeddings"])
        self.assertEqual(captured[0][1]["thinking"], {"type": "enabled"})
        self.assertEqual(captured[0][1]["reasoning_effort"], "low")
        self.assertEqual(adapter.budget.known_tokens, 15)
        for path in store.path.rglob("*"):
            if path.is_file():
                self.assertNotIn("unit-secret", path.read_text())

    def test_failed_batch_and_unit_are_marked_and_analysis_refuses(self):
        args = parser().parse_args(["--run-id", "failure", "--output-root", str(self.root)])
        with patch("run.MockAdapter._dispatch", side_effect=ValueError("malformed")), patch("llm_adapter.time.sleep"):
            with self.assertRaises(RuntimeError):
                execute(args)
        path = self.root / "mock" / "failure"
        self.assertEqual(read_json(path / "batch.json")["status"], "failed")
        self.assertEqual(read_json(path / "rep_01/baseline/manifest.json")["status"], "failed")
        with self.assertRaises(ValueError):
            analyze(path, self.root / "bad_results")

    def test_end_to_end_shared_baseline_metrics_and_call_counts(self):
        args = parser().parse_args(["--run-id", "integration", "--output-root", str(self.root)])
        path = execute(args)
        output = analyze(path, self.root / "results")
        metrics = read_json(output / "metrics.json")
        self.assertEqual(metrics["costs"]["text_requests"], 132)
        self.assertTrue(metrics["semantic_labels_complete"])
        with (output / "node_states.csv").open(encoding="utf-8-sig") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 72)
        for condition, first, reach_time in [("B", 2, 3), ("C", 1, 2)]:
            subset = [m for m in metrics["rounds"] if m["condition"] == condition]
            self.assertEqual(subset[-1]["first_cross_round"], first)
            self.assertEqual(next(m["round"] for m in subset if m["correction_reached"] == 6), reach_time)
        self.assertTrue(all(m["correction_reached"] == 0 for m in metrics["rounds"] if m["condition"] == "A"))
        for condition in ("A", "B", "C"):
            unit = path / "rep_01" / condition
            states, _, deliveries = verify_unit(unit, self.config)
            self.assertEqual(len(states), 24)
            self.assertTrue(all(d["received_round"] <= 3 for d in deliveries))
            calls = rows(unit / "calls.jsonl")
            self.assertEqual(sum(c["kind"] == "text" for c in calls), 42)
        # Each of the two groups' databases is independent (one collection per run).
        self.assertNotEqual((path / "rep_01/B/memory").resolve(), (path / "rep_01/C/memory").resolve())


if __name__ == "__main__":
    unittest.main()
