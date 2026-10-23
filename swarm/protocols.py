"""Inter-agent message schema.

Every message carries a trace id (kernel.correlation), a kind, and a
sender identity. Payloads are plain dicts so messages serialize cleanly
to memory/logs/audit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kernel.correlation import new_id


class MessageKind(str, Enum):
    TASK = "task"              # ask a peer to do something
    RESULT = "result"          # completed work
    QUESTION = "question"      # clarification request
    CRITIQUE = "critique"      # review feedback
    INFO = "info"              # FYI / blackboard updates
    CONTROL = "control"        # start/stop/cancel


@dataclass
class Sender:
    name: str
    role: str = "worker"       # planner | worker | critic | synthesizer | operator

    def describe(self) -> dict:
        return {"name": self.name, "role": self.role}


@dataclass
class AgentMessage:
    kind: MessageKind
    sender: Sender
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    trace_id: str = field(default_factory=new_id)
    in_reply_to: str | None = None
    created_at: float = field(default_factory=time.time)

    def reply(self, kind: MessageKind, payload: dict[str, Any]) \
            -> "AgentMessage":
        return AgentMessage(kind=kind, sender=self.sender, payload=payload,
                            trace_id=self.trace_id, in_reply_to=self.id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind.value,
                "sender": self.sender.describe(), "payload": self.payload,
                "trace_id": self.trace_id,
                "in_reply_to": self.in_reply_to,
                "created_at": self.created_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        return cls(kind=MessageKind(data["kind"]),
                   sender=Sender(**data["sender"]),
                   payload=data.get("payload", {}),
                   id=data["id"], trace_id=data.get("trace_id", new_id()),
                   in_reply_to=data.get("in_reply_to"),
                   created_at=data.get("created_at", time.time()))
