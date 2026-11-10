"""CLI: frozen baselines, isolated conditions, mock/real backends and failure manifests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import sys
import uuid

from common import ROOT, Store, load_inputs, snapshot, write_json, validate_decision
from llm_adapter import Budget, RealAdapter
from mock_llm import MockAdapter
from model import ClarificationModel


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def run_unit(path, adapter, config, personas, materials, mapping, repeat, condition, baseline=None):
    store = Store(path)
    manifest = {"backend": adapter.backend, "status": "running", "repeat": repeat,
                "condition": condition, "started_at": timestamp(),
                "mapping": mapping, "effective_api": adapter.public_settings(),
                "snapshot": snapshot(config, personas, materials)}
    store.save("manifest.json", manifest)
    model = None
    try:
        with adapter.scope(store, stage="create_model", repeat=repeat, condition=condition):
            model = ClarificationModel(config, personas, materials, mapping, adapter, store, repeat, condition)
        if condition is None:
            result = model.baseline()
        else:
            model.initialize(baseline)
            for _ in range(config["rounds"]):
                model.step()
            result = None
        manifest["status"] = "complete"
        return result
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["error_type"] = type(error).__name__
        raise
    finally:
        manifest["completed_round"] = model.completed_round if model else None
        manifest["finished_at"] = timestamp()
        store.save("manifest.json", manifest)


def connectivity_check(path, adapter, config):
    import chromadb
    store = Store(path)
    status = {"status": "running", "backend": adapter.backend, "effective_api": adapter.public_settings()}
    store.save("manifest.json", status)
    try:
        payload = {"task": "initial", "persona": "倾向核实", "materials": [{"text": "听说打印服务下周要涨价。"}]}
        prompt = "只返回包含 belief_price_increase、opinion、message、share 的 JSON，数值在0到1之间，share为布尔值。\n<<<CONTEXT>>>\n" + json.dumps(payload, ensure_ascii=False) + "\n<<<END>>>"
        with adapter.scope(store, stage="connectivity", repeat=0, node=0):
            decision = adapter.generate(prompt, validate_decision, json_flag=True)
            plain = adapter.send_message(prompt)
            collection = chromadb.PersistentClient(path=str(store.path / "memory")).get_or_create_collection(
                "connectivity", embedding_function=adapter.get_lang_embedding())
            collection.add(ids=["one", "two"], documents=["打印服务", "营业时间"])
            result = collection.query(query_texts=["打印服务"], n_results=1)
            assert result["ids"][0]
        store.save("check.json", {"decision": decision, "text_response_nonempty": bool(plain),
                                  "embedding_dimension": adapter.embedding_dimension,
                                  "query_ids": result["ids"]})
        status["status"] = "complete"
    except BaseException as error:
        status.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        store.save("manifest.json", status)


def execute(args):
    config, personas, materials = load_inputs(args.config)
    repeats = args.repeats if args.repeats is not None else (3 if args.phase == "formal" else 1)
    conditions = args.conditions or (["C"] if args.phase == "pilot" else ["A", "B", "C"])
    if repeats < 1 or repeats > len(personas["mappings"]):
        raise ValueError("repeats must be between 1 and the number of frozen mappings (3)")
    if len(set(conditions)) != len(conditions):
        raise ValueError("Duplicate conditions are not allowed")
    if args.phase == "formal" and (set(conditions) != {"A", "B", "C"} or repeats != 3 or args.backend != "real"):
        raise ValueError("Formal runs require real backend, all A/B/C conditions and 3 repeats; use phase mock for fixtures")
    if args.backend == "mock" and args.phase not in ("mock", "check"):
        raise ValueError("Mock backend must use phase mock or check")
    if args.backend == "real" and args.phase == "mock":
        raise ValueError("Real backend must use phase check, pilot or formal")
    budget = Budget(config, args.backend)
    adapter = MockAdapter(config, budget) if args.backend == "mock" else RealAdapter(config, budget)
    run_id = args.run_id or ("batch_" + uuid.uuid4().hex[:10])
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("run-id may contain only letters, digits, underscore and hyphen")
    base = Path(args.output_root or ROOT / "runs") / args.phase / run_id
    base.mkdir(parents=True, exist_ok=False)
    batch = {"status": "running", "backend": args.backend, "phase": args.phase,
             "conditions": conditions, "repeats": repeats, "started_at": timestamp(),
             "effective_api": adapter.public_settings(), "snapshot": snapshot(config, personas, materials)}
    write_json(base / "batch.json", batch)
    # Preserve exact protocol/templates used, in addition to hashes and full request logs.
    (base / "protocol.md").write_text((ROOT / "protocol.md").read_text(encoding="utf-8"), encoding="utf-8")
    (base / "templates").mkdir()
    for path in (ROOT / "prompts").glob("*.txt"):
        (base / "templates" / path.name).write_bytes(path.read_bytes())
    try:
        if args.phase == "check":
            connectivity_check(base / "connectivity", adapter, config)
        else:
            for repeat in range(1, repeats + 1):
                mapping = personas["mappings"][repeat - 1]
                rep_path = base / f"rep_{repeat:02d}"
                baseline = run_unit(rep_path / "baseline", adapter, config, personas, materials, mapping, repeat, None)
                write_json(rep_path / "baseline.json", baseline)
                offset = (repeat - 1) % len(conditions)
                order = conditions[offset:] + conditions[:offset]
                for condition in order:
                    print(f"[{args.backend}] repeat {repeat}: condition {condition}", flush=True)
                    run_unit(rep_path / condition, adapter, config, personas, materials, mapping, repeat, condition, baseline)
        batch["status"] = "complete"
    except BaseException as error:
        batch.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        batch["finished_at"] = timestamp()
        batch["budget"] = budget.report()
        write_json(base / "batch.json", batch)
        print(f"Output: {base}", flush=True)
    return base


def parser():
    p = argparse.ArgumentParser(description="Casevo campus clarification experiment")
    p.add_argument("--backend", choices=["mock", "real"], default="mock")
    p.add_argument("--phase", choices=["mock", "check", "pilot", "formal"], default="mock")
    p.add_argument("--conditions", nargs="+", choices=["A", "B", "C"])
    p.add_argument("--repeats", type=int)
    p.add_argument("--run-id")
    p.add_argument("--config", type=Path)
    p.add_argument("--output-root", type=Path)
    return p


if __name__ == "__main__":
    try:
        execute(parser().parse_args())
    except Exception as error:
        # Adapter errors contain no server response bodies or credentials.
        print(f"Stopped: {error}", file=sys.stderr)
        sys.exit(1)
