"""Synchronous network experiment built on Casevo ModelBase and memory factory."""
from __future__ import annotations

import copy
import json

import networkx as nx

from casevo import ModelBase
from agent import ClarificationAgent
from common import ROOT


class ClarificationModel(ModelBase):
    def __init__(self, config, personas, materials, mapping, llm, store, repeat=1, condition=None, order=None):
        graph = nx.Graph()
        graph.add_nodes_from(config["nodes"])
        graph.add_edges_from(config["edges"])
        self.config, self.store, self.repeat, self.condition = config, store, repeat, condition
        self.materials = materials
        super().__init__(graph, llm, prompt_path=str(ROOT / "prompts"), memory_path=str(store.path / "memory"))
        self.order = list(config["nodes"] if order is None else order)
        if sorted(self.order) != config["nodes"]:
            raise ValueError("Execution order must be a permutation of all nodes")
        self.nodes = {}
        for node in config["nodes"]:
            role = mapping[str(node)]
            agent = ClarificationAgent(node, self, role, personas["roles"][role])
            self.nodes[node] = agent
            self.add_agent(agent, node)
        self.messages = []
        self.completed_round = -1

    def render(self, filename, payload):
        return self.prompt_factory.env.get_template(filename).render(
            payload=json.dumps(payload, ensure_ascii=False, allow_nan=False))

    def scope(self, stage, round_, node):
        return self.llm.scope(self.store, **{"stage": stage, "round": round_, "node": node,
                                            "repeat": self.repeat, "condition": self.condition})

    def baseline(self):
        results = {}
        for node in self.order:
            agent = self.nodes[node]
            with self.scope("baseline", "pre", node):
                agent.state = agent.decide(agent.decision_payload("initial", materials=[self.materials["rumor"]]), initial=True)
            row = agent.export("pre")
            results[str(node)] = copy.deepcopy(agent.state)
            self.store.append("states", row)
        return results

    def initialize(self, baseline):
        recipient = self.config["conditions"][self.condition]
        self.schedule.time = 0
        next_states = {}
        for node in self.order:
            agent = self.nodes[node]
            agent.state = copy.deepcopy(baseline[str(node)])
            visible = [self.materials["rumor"]]
            if node == recipient:
                visible.append(self.materials["clarification"])
            with self.scope("initialize", 0, node):
                for item in visible:
                    agent.remember("external_notice" if item["id"] == "C0" else "external_rumor",
                                   item["text"], "material", 0, item["id"])
                payload = agent.decision_payload("initial", materials=visible)
                next_states[node] = agent.decide(payload, initial=True)
        for node, state in next_states.items():
            self.nodes[node].state = state
        self._record_outputs(0, reflect=False)
        self.completed_round = 0

    def freeze_inboxes(self, round_):
        boxes = {node: [] for node in self.config["nodes"]}
        for message in self.messages:
            if not message["share"]:
                continue
            if message["round"] != round_ - 1:
                raise ValueError("Only previous-round messages may be delivered")
            for target in sorted(self.grid.G.neighbors(message["sender"])):
                boxes[target].append({"id": f"d{round_}_{message['sender']}_{target}",
                                      "message_id": message["id"], "sender": message["sender"],
                                      "recipient": target, "sent_round": message["round"],
                                      "received_round": round_, "text": message["text"]})
        return boxes

    def step(self):
        round_ = self.completed_round + 1
        if not 1 <= round_ <= self.config["rounds"]:
            raise ValueError("No valid next round")
        self.schedule.time = round_
        inboxes = self.freeze_inboxes(round_)
        payloads = {}
        # Finish ALL deliveries and retrieve frozen inputs before any decision is generated.
        for node in self.order:
            agent = self.nodes[node]
            with self.scope("receive_retrieve", round_, node):
                for delivery in inboxes[node]:
                    assert self.grid.G.has_edge(delivery["sender"], node)
                    self.store.append("deliveries", delivery)
                    agent.remember(f"agent_{delivery['sender']}", delivery["text"], "receive", round_, delivery["id"])
                memories = agent.retrieve(round_)
                # Public inbox contains only actual speech and source, never private scores.
                public = [{"sender": d["sender"], "text": d["text"], "message_id": d["message_id"]} for d in inboxes[node]]
                payloads[node] = agent.decision_payload("update", inbox=public, memories=memories)
        outputs = {}
        for node in self.order:
            with self.scope("decision", round_, node):
                outputs[node] = self.nodes[node].decide(payloads[node])
        for node, state in outputs.items():
            self.nodes[node].state = state
        self._record_outputs(round_, reflect=True)
        self.completed_round = round_
        self.schedule.steps = round_
        return 0

    def _record_outputs(self, round_, reflect):
        next_messages = []
        for node in self.order:
            agent = self.nodes[node]
            message = {"id": f"m{round_}_{node}", "round": round_, "sender": node,
                       "text": agent.state["message"], "share": agent.state["share"]}
            self.store.append("messages", message)
            next_messages.append(message)
            with self.scope("record_reflect" if reflect else "record", round_, node):
                agent.remember(agent.component_id, agent.state["message"], "own_output", round_, message["id"])
                if reflect:
                    agent.reflect(round_)
            self.store.append("states", agent.export(round_))
        self.messages = next_messages
