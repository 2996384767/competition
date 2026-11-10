"""Shared run files, configuration checks and immutable protocol snapshots."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically so an interrupted write cannot look like a completed result.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=False)
        for name in ("prompts", "responses"):
            (self.path / name).mkdir()
        for name in ("states", "messages", "deliveries", "memory_trace", "calls", "annotations"):
            (self.path / (name + ".jsonl")).touch()

    def append(self, name, item):
        with (self.path / (name + ".jsonl")).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")

    def save(self, name, item):
        write_json(self.path / name, item)


def validate_decision(text):
    # Deliberately reject fences, extra fields and coerced strings.
    item = json.loads(text)
    fields = {"belief_price_increase", "opinion", "message", "share"}
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError("Decision must contain exactly the four protocol fields")
    value = item["belief_price_increase"]
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Belief must be a finite number in [0, 1]")
    if type(item["share"]) is not bool:
        raise ValueError("share must be a JSON boolean")
    for field in ("opinion", "message"):
        if not isinstance(item[field], str) or len(item[field]) > 3000:
            raise ValueError("Invalid decision text")
    if not item["opinion"].strip() or (item["share"] and not item["message"].strip()):
        raise ValueError("Required decision text is empty")
    return item


def validate_reflection(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise ValueError("Reflection must be nonempty text of at most 1000 characters")
    return text.strip()


def load_inputs(config_path=None):
    config = read_json(config_path or ROOT / "config.json")
    personas = read_json(ROOT / "personas.json")
    materials = read_json(ROOT / "materials.json")
    if config["nodes"] != list(range(1, 7)) or config["rounds"] != 3:
        raise ValueError("Protocol 1.0 requires nodes 1..6 and exactly 3 rounds")
    edges = {tuple(sorted(edge)) for edge in config["edges"]}
    if len(config["edges"]) != 7 or edges != {(1, 2), (1, 3), (2, 3), (3, 4), (4, 5), (4, 6), (5, 6)}:
        raise ValueError("Network differs from the frozen protocol")
    if config["conditions"] != {"A": None, "B": 1, "C": 3}:
        raise ValueError("Conditions differ from the frozen protocol")
    if config["groups"] != {"G1": [1, 2, 3], "G2": [4, 5, 6]}:
        raise ValueError("Groups differ from the frozen protocol")
    for key in ("retrieval_k", "max_attempts", "max_output_tokens", "max_prompt_chars"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"Invalid {key}")
    if config["max_attempts"] > 3:
        raise ValueError("At most 3 total attempts per logical call")
    for mapping in personas["mappings"]:
        if set(mapping) != set(map(str, config["nodes"])) or set(mapping.values()) != set(personas["roles"]):
            raise ValueError("Each mapping must assign the six distinct roles once")
    return config, personas, materials


def snapshot(config, personas, materials):
    files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "prompts").glob("*.txt")) + [ROOT / "protocol.md"]
    return {
        "config": config, "personas": personas, "materials": materials,
        "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "dependencies": {p: importlib.metadata.version(p) for p in ("casevo", "mesa", "chromadb", "jinja2", "httpx", "matplotlib")},
    }
