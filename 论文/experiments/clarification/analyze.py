"""Recompute metrics from complete logs; real semantic labels require human review."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import ROOT, read_json, write_json


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare_annotations(unit, backend):
    path = unit / "annotations.jsonl"
    existing = {(r["kind"], r["id"]): r for r in rows(path)}
    proposed = []
    for message in rows(unit / "messages.jsonl"):
        corrected = "价格保持不变" in message["text"]
        proposed.append({"kind": "message", "id": message["id"], "text": message["text"],
                         "status": "mock_fixture" if backend == "mock" else "pending",
                         "correction_content": corrected if backend == "mock" else None,
                         "full_correction": corrected if backend == "mock" else None,
                         "asserts_increase": False if backend == "mock" else None,
                         "evidence": message["text"] if backend == "mock" else "",
                         "reviewer": "deterministic fixture" if backend == "mock" else ""})
    for state in rows(unit / "states.jsonl"):
        corrected = "价格保持不变" in (state["long_memory"] or "")
        proposed.append({"kind": "state", "id": f"r{state['round']}_n{state['node']}",
                         "opinion": state["opinion"], "long_memory": state["long_memory"],
                         "status": "mock_fixture" if backend == "mock" else "pending",
                         "opinion_stance": ("accepted" if state["belief_price_increase"] <= 0.3 else "uncertain") if backend == "mock" else None,
                         "memory_retention": ("not_applicable" if state["round"] == 0 else "preserved" if corrected else "omitted") if backend == "mock" else None,
                         "evidence": state["long_memory"] or state["opinion"] if backend == "mock" else "",
                         "reviewer": "deterministic fixture" if backend == "mock" else ""})
    # Existing human work is never overwritten by regenerating templates.
    with path.open("w", encoding="utf-8") as stream:
        for item in proposed:
            stream.write(json.dumps(existing.get((item["kind"], item["id"]), item), ensure_ascii=False) + "\n")


def annotations_complete(annotations, backend):
    allowed = {"mock_fixture"} if backend == "mock" else {"reviewed"}
    for item in annotations:
        if item["status"] not in allowed:
            return False
        if item["kind"] == "message":
            if any(type(item.get(k)) is not bool for k in ("correction_content", "full_correction", "asserts_increase")):
                raise ValueError("Reviewed message labels must be booleans")
        else:
            if item.get("opinion_stance") not in {"accepted", "uncertain", "rejected", "inconsistent"}:
                raise ValueError("Invalid reviewed opinion stance")
            if item.get("memory_retention") not in {"preserved", "omitted", "distorted", "not_applicable"}:
                raise ValueError("Invalid reviewed memory label")
        if backend == "real" and (not item.get("evidence") or not item.get("reviewer")):
            raise ValueError("Reviewed real annotations require evidence and reviewer")
    return bool(annotations)


def verify_unit(unit, config):
    manifest = read_json(unit / "manifest.json")
    if manifest["status"] != "complete":
        raise ValueError(f"Incomplete run: {unit}")
    states = rows(unit / "states.jsonl")
    if len(states) != 24 or {(s["round"], s["node"]) for s in states} != {(t, n) for t in range(4) for n in config["nodes"]}:
        raise ValueError("Missing or duplicate node states")
    messages = rows(unit / "messages.jsonl")
    by_id = {m["id"]: m for m in messages}
    if len(messages) != 24 or len(by_id) != 24:
        raise ValueError("Missing or duplicate messages")
    deliveries = rows(unit / "deliveries.jsonl")
    edges = {tuple(sorted(e)) for e in config["edges"]}
    ids = set()
    for d in deliveries:
        if d["id"] in ids:
            raise ValueError("Duplicate delivery")
        ids.add(d["id"])
        m = by_id[d["message_id"]]
        if (not m["share"] or m["sender"] != d["sender"] or m["text"] != d["text"]
                or d["received_round"] != m["round"] + 1 or d["sent_round"] != m["round"]
                or tuple(sorted((d["sender"], d["recipient"]))) not in edges):
            raise ValueError("Illegal or asynchronous delivery")
    expected = {(m["id"], target) for m in messages if m["share"] and m["round"] < 3
                for target in config["nodes"] if tuple(sorted((m["sender"], target))) in edges}
    if {(d["message_id"], d["recipient"]) for d in deliveries} != expected:
        raise ValueError("Missing or extra network deliveries")
    return states, messages, deliveries


def analyze(batch_path, output=None):
    batch_path = Path(batch_path).resolve()
    batch = read_json(batch_path / "batch.json")
    if batch["status"] != "complete" or batch["phase"] == "check":
        raise ValueError("Analysis requires a complete experiment batch")
    backend = batch["backend"]
    config = batch["snapshot"]["config"]
    output = Path(output or ROOT / "results" / batch_path.name)
    if output.exists():
        raise FileExistsError("Results directory already exists; choose a new --output")
    units = []
    for repeat in range(1, batch["repeats"] + 1):
        rep = batch_path / f"rep_{repeat:02d}"
        baseline = read_json(rep / "baseline.json")
        for condition in batch["conditions"]:
            unit = rep / condition
            states, messages, deliveries = verify_unit(unit, config)
            prepare_annotations(unit, backend)
            annotations = rows(unit / "annotations.jsonl")
            complete = annotations_complete(annotations, backend)
            units.append((repeat, condition, unit, baseline, states, messages, deliveries, annotations, complete))
    output.mkdir(parents=True, exist_ok=False)
    metrics, node_rows, paths, paired = [], [], [], []
    all_labels_complete = all(u[-1] for u in units)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    colors = {"A": "#777777", "B": "#2478b5", "C": "#dd7733"}
    for repeat, condition, unit, baseline, states, messages, deliveries, annotations, complete in units:
        labels = {(a["kind"], a["id"]): a for a in annotations}
        recipient = config["conditions"][condition]
        reached = {recipient: 0} if recipient else {}
        trace_deliveries = []
        if complete:
            for d in sorted(deliveries, key=lambda x: (x["received_round"], x["id"])):
                if labels[("message", d["message_id"])]["correction_content"] and reached.get(d["sender"], 999) <= d["sent_round"]:
                    reached.setdefault(d["recipient"], d["received_round"])
                    trace_deliveries.append(d)
        pre = statistics.mean(s["belief_price_increase"] for s in baseline.values())
        means = []
        for t in range(4):
            current = [s for s in states if s["round"] == t]
            mean = statistics.mean(s["belief_price_increase"] for s in current)
            means.append(mean)
            first_cross = min((d["received_round"] for d in trace_deliveries if d["recipient"] in config["groups"]["G2"]), default=None)
            exposed = {node for node, time in reached.items() if time <= t}
            # Final-round outputs are generated but never count as actual transmissions.
            sent = [m for m in messages if m["round"] <= t]
            propagated = [m for m in messages if m["round"] < t and m["share"]]
            generated_wrong = sum(labels[("message", m["id"])]["asserts_increase"] for m in sent) if complete else None
            transmitted_wrong = sum(labels[("message", m["id"])]["asserts_increase"] for m in propagated) if complete else None
            delivered_wrong = sum(labels[("message", d["message_id"])]["asserts_increase"] for d in deliveries if d["received_round"] <= t) if complete else None
            memory_counts = {key: 0 for key in ("preserved", "omitted", "distorted")}
            if complete and t > 0:
                for s in current:
                    if s["node"] in exposed:
                        key = labels[("state", f"r{t}_n{s['node']}")]["memory_retention"]
                        if key in memory_counts:
                            memory_counts[key] += 1
            metrics.append({"repeat": repeat, "condition": condition, "round": t,
                            "mean_belief": mean, "baseline_mean": pre, "decrease_from_pre": pre - mean,
                            "mean_other_five": statistics.mean(s["belief_price_increase"] for s in current if s["node"] != recipient) if recipient else None,
                            "direct_recipients": int(recipient is not None),
                            "correction_reached": len(exposed) if complete else None,
                            "network_new_reached": len(exposed - {recipient}) if complete else None,
                            "first_cross_round": first_cross if complete and first_cross is not None and first_cross <= t else None,
                            "wrong_generated": generated_wrong, "wrong_messages_transmitted": transmitted_wrong,
                            "wrong_deliveries": delivered_wrong,
                            "memory_retention": memory_counts if complete and t > 0 else None,
                            "semantic_labels_complete": complete})
            for s in current:
                label = labels[("state", f"r{t}_n{s['node']}")]
                exposure = s["node"] in exposed if complete else None
                node_rows.append({"repeat": repeat, "condition": condition, **s,
                                  "correction_received": exposure,
                                  "low_belief": s["belief_price_increase"] <= 0.3,
                                  "opinion_stance": label.get("opinion_stance"),
                                  "accepts_received_correction": (exposure and s["belief_price_increase"] <= 0.3 and label["opinion_stance"] == "accepted") if complete else None,
                                  "memory_retention": label.get("memory_retention"), "annotation_status": label["status"],
                                  "message_id": f"m{t}_{s['node']}"})
        ax.plot([-1, 0, 1, 2, 3], [pre] + means, marker="o", color=colors[condition],
                alpha=0.65, label=f"{condition} / repeat {repeat}")
        paths.append(f"## Repeat {repeat}, condition {condition}\n")
        if not complete:
            paths.append("人工标注尚未完成，传播与接受指标留空。请编辑本条件 annotations.jsonl 后重新分析。\n")
        elif not trace_deliveries:
            paths.append("未观察到来源可追溯的网络澄清传播。\n")
        else:
            for d in trace_deliveries:
                safe = d["text"].replace("\n", " ")
                paths.append(f"- t={d['received_round']}：{d['sender']} → {d['recipient']}，消息 {d['message_id']}，投递 {d['id']}：{safe}\n")
        paths.append("来源追溯仅表示存在实际投递路径，不证明某条消息单独导致了观点变化。\n")
    for repeat in range(1, batch["repeats"] + 1):
        last = {m["condition"]: m["mean_belief"] for m in metrics if m["repeat"] == repeat and m["round"] == 3}
        if set(last) == {"A", "B", "C"}:
            paired.append({"repeat": repeat, "B_minus_C": last["B"] - last["C"],
                           "A_minus_B": last["A"] - last["B"], "A_minus_C": last["A"] - last["C"]})
    ax.set(ylim=(0, 1), xlabel="Time (pre = before intervention)", ylabel="Self-reported belief in price increase",
           title="MOCK FIXTURE - not empirical evidence" if backend == "mock" else "Clarification experiment")
    ax.set_xticks([-1, 0, 1, 2, 3], ["pre", "0", "1", "2", "3"])
    ax.legend(fontsize=7)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output / "belief_curve.png", dpi=160)
    plt.close(fig)
    with (output / "node_states.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(node_rows[0]))
        writer.writeheader()
        writer.writerows(node_rows)
    all_calls = [call for path in batch_path.rglob("calls.jsonl") for call in rows(path)]
    costs = {"actual_requests": len(all_calls), "text_requests": sum(c["kind"] == "text" for c in all_calls),
             "embedding_requests": sum(c["kind"] == "embedding" for c in all_calls),
             "embedding_texts": sum(c["input_text_count"] for c in all_calls if c["kind"] == "embedding"),
             "failed_attempts": sum(c["status"] != "success" for c in all_calls),
             "retry_requests": sum(c["attempt"] > 1 for c in all_calls),
             "usage_unknown_requests": sum(c["usage"] is None for c in all_calls),
             "reported_tokens": sum((c["usage"] or {}).get("total_tokens", 0) for c in all_calls),
             "request_seconds": sum(c["elapsed_seconds"] for c in all_calls)}
    write_json(output / "metrics.json", {"backend": backend, "source": str(batch_path),
                                        "semantic_labels_complete": all_labels_complete,
                                        "rounds": metrics, "paired": paired, "costs": costs})
    (output / "message_paths.md").write_text("# 消息传播记录\n\n" + ("**模拟规则输出，不代表真实行为。**\n\n" if backend == "mock" else "") + "\n".join(paths), encoding="utf-8")
    lines = ["# 实验结果\n", "**模拟规则输出，仅用于机制验收，不能用于支持干预效果结论。**\n" if backend == "mock" else "真实模型实验；结论限于本协议与样本。\n",
             f"来源：{batch_path}\n", f"语义标注完整：{all_labels_complete}。真实运行 pending 标签须人工复核后改为 reviewed。\n",
             "| 重复 | B末轮均值−C末轮均值 | A−B | A−C |\n| --- | --- | --- | --- |"]
    lines += [f"| {p['repeat']} | {p['B_minus_C']:.4f} | {p['A_minus_B']:.4f} | {p['A_minus_C']:.4f} |" for p in paired]
    lines += ["\n正值仅表示该重复中相应末轮误信均值更低。\n",
              "节点3比节点1多一个邻居，不能单独归因于桥接作用。三次以内重复只作探索。未在观察窗口内跨群体传播不记作0轮。\n",
              "## 请求用量\n", "```json\n" + json.dumps(costs, ensure_ascii=False, indent=2) + "\n```\n",
              "Token 缺失记为未知；本地预算中的估算量不是服务方实测用量。具体金额需依实际服务价格另算。\n"]
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Results: {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    analyze(args.batch, args.output)
