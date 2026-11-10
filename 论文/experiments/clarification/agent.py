"""Casevo agents with explicit, auditable prompt assembly."""
from __future__ import annotations

import copy
import json

from casevo import AgentBase

from common import validate_decision, validate_reflection


class ClarificationAgent(AgentBase):
    def __init__(self, node, model, role_id, description):
        super().__init__(node, model, description, None)
        self.role_id = role_id
        self.state = None
        self.memory_version = 0
        self.current_experiences = []

    def remember(self, source, content, action, round_, reference=None):
        collection = self.model.memory_factory.memory_collection
        index = collection.count()
        self.memory.add_short_memory(source, self.component_id, action, content, ts=round_)
        self.current_experiences.append({"source": source, "text": content, "action": action})
        self.model.store.append("memory_trace", {
            "event": "write", "node": self.unique_id, "round": round_,
            "memory_id": str(index), "source": source, "target": self.component_id,
            "action": action, "reference": reference,
        })

    def retrieve(self, round_):
        collection = self.model.memory_factory.memory_collection
        query = "下周打印是否涨价，收到的通知、传闻和交流来源"
        count = collection.count()
        if count:
            result = collection.query(
                query_texts=[query], n_results=min(self.model.config["retrieval_k"], count),
                where={"$or": [{"source": self.component_id}, {"target": self.component_id}]},
            )
            memories = [{"id": id_, "text": doc, "metadata": metadata}
                        for id_, doc, metadata in zip(result["ids"][0], result["documents"][0], result["metadatas"][0])]
        else:
            memories = []
        self.model.store.append("memory_trace", {
            "event": "retrieve", "node": self.unique_id, "round": round_, "query": query,
            "ids": [item["id"] for item in memories],
            "long_memory_version": self.memory_version, "long_memory": self.memory.long_memory,
        })
        return memories

    def decision_payload(self, task, materials=None, inbox=None, memories=None):
        return {"task": task, "persona": self.description,
                "previous_state": copy.deepcopy(self.state), "materials": materials or [],
                "inbox": inbox or [], "relevant_memories": memories or [],
                "long_memory": self.memory.long_memory}

    def decide(self, payload, initial=False):
        template = "initial.txt" if initial else "update.txt"
        prompt = self.model.render(template, payload)
        return self.model.llm.generate(prompt, validate_decision, json_flag=True)

    def reflect(self, round_):
        payload = {"task": "reflect", "persona": self.description,
                   "old_long_memory": self.memory.long_memory,
                   "new_experiences": copy.deepcopy(self.current_experiences),
                   "own_state": copy.deepcopy(self.state)}
        result = self.model.llm.generate(self.model.render("reflect.txt", payload), validate_reflection)
        self.memory.long_memory = result
        self.memory.last_id = self.model.memory_factory.memory_collection.count() - 1
        self.memory_version += 1
        self.current_experiences = []
        self.model.store.append("memory_trace", {
            "event": "reflect", "node": self.unique_id, "round": round_,
            "long_memory_version": self.memory_version, "long_memory": result,
        })

    def export(self, round_):
        return {"round": round_, "node": self.unique_id, "role": self.role_id,
                **copy.deepcopy(self.state), "long_memory": self.memory.long_memory,
                "long_memory_version": self.memory_version}

    def step(self):
        raise RuntimeError("Use the model's synchronous step, not random agent activation")
