from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VariableSpec:
    key: str
    label: str
    default: str = ""
    placeholder: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VariableSpec":
        return cls(
            key=str(data["key"]),
            label=str(data.get("label") or data["key"]),
            default=str(data.get("default") or ""),
            placeholder=str(data.get("placeholder") or ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "default": self.default,
            "placeholder": self.placeholder,
        }


@dataclass
class Task:
    id: str
    title: str
    role: str
    task: str
    opening_line: str
    response_limit: str
    flow: list[str]
    knowledge: list[str]
    constraints: list[str]
    variables: list[VariableSpec] = field(default_factory=list)
    quick_replies: list[str] = field(default_factory=list)
    raw_instruction: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            role=str(data["role"]),
            task=str(data["task"]),
            opening_line=str(data["opening_line"]),
            response_limit=str(data.get("response_limit") or ""),
            flow=[str(item) for item in data.get("flow", [])],
            knowledge=[str(item) for item in data.get("knowledge", [])],
            constraints=[str(item) for item in data.get("constraints", [])],
            variables=[VariableSpec.from_dict(item) for item in data.get("variables", [])],
            quick_replies=[str(item) for item in data.get("quick_replies", [])],
            raw_instruction=str(data.get("raw_instruction") or ""),
        )

    def defaults(self) -> dict[str, str]:
        return {item.key: item.default for item in self.variables}

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "role": self.role,
            "task": self.task,
            "response_limit": self.response_limit,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "opening_line": self.opening_line,
            "flow": self.flow,
            "knowledge": self.knowledge,
            "constraints": self.constraints,
            "variables": [item.to_dict() for item in self.variables],
            "quick_replies": self.quick_replies,
            "raw_instruction": self.raw_instruction,
        }


@dataclass
class Message:
    role: str
    content: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content, "ts": self.ts}


@dataclass
class Session:
    task_id: str
    variables: dict[str, str]
    mode: str = "rule"
    llm_config: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stage: int = 0
    status: str = "opening"
    ended: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add(self, role: str, content: str) -> Message:
        message = Message(role=role, content=content)
        self.messages.append(message)
        return message

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "variables": self.variables,
            "mode": self.mode,
            "llm": {
                "configured": bool(
                    self.llm_config.get("api_key") and self.llm_config.get("model")
                ),
                "has_api_key": bool(self.llm_config.get("api_key")),
                "base_url": self.llm_config.get("base_url", ""),
                "model": self.llm_config.get("model", ""),
            },
            "stage": self.stage,
            "status": self.status,
            "ended": self.ended,
            "meta": self.meta,
            "messages": [item.to_dict() for item in self.messages],
            "created_at": self.created_at,
        }
