from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from outbound_agent.config import load_llm_config, public_llm_config
from outbound_agent.models import Session, Task


class LLMClient:
    """Small OpenAI-compatible client with no third-party dependency."""

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path

    @property
    def available(self) -> bool:
        config = load_llm_config(self.config_path)
        return bool(config["api_key"] and config["model"])

    def config_status(self) -> dict[str, Any]:
        return public_llm_config(self.config_path)

    def reply(self, task: Task, session: Session, user_text: str) -> str:
        api_key, model, endpoint = self._resolve_config(session)
        if not api_key or not model:
            raise RuntimeError("LLM is not configured")
        data = self._post_chat(
            endpoint,
            api_key,
            {
                "model": model,
                "messages": self._messages(task, session, user_text),
                "temperature": 0.4,
            },
            model,
        )
        return str(data["choices"][0]["message"]["content"]).strip()

    def generate_voice_reply(
        self,
        task: Task,
        session: Session,
        user_text: str,
        plan: dict[str, Any],
    ) -> str:
        """Generate one phone-call reply from a deterministic business reply plan."""
        api_key, model, endpoint = self._resolve_config(session)
        if not api_key or not model:
            raise RuntimeError("LLM is not configured")
        messages = self.build_voice_agent_messages(task, session, user_text, plan)
        data = self._post_chat(
            endpoint,
            api_key,
            {
                "model": model,
                "messages": messages,
                "temperature": 0.25,
                "max_tokens": 120,
            },
            model,
        )
        return str(data["choices"][0]["message"]["content"]).strip()

    def reply_from_plan(
        self,
        task: Task,
        session: Session,
        user_text: str,
        plan: dict[str, Any],
    ) -> str:
        """Backward-compatible alias for tests or older callers."""
        return self.generate_voice_reply(task, session, user_text, plan)

    def test_connection(self, config: dict[str, str] | None = None) -> dict[str, Any]:
        config = config or {}
        api_key, model, endpoint = self._resolve_values(config)
        if not api_key:
            raise RuntimeError("API Key is required")
        if not model:
            raise RuntimeError("Model is required")
        data = self._post_chat(
            endpoint,
            api_key,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是连接测试助手。"},
                    {"role": "user", "content": "请只回复 OK"},
                ],
                "temperature": 0,
                "max_tokens": 8,
            },
            model,
            timeout=12,
        )
        content = str(data["choices"][0]["message"]["content"]).strip()
        return {"ok": True, "endpoint": endpoint, "model": model, "reply": content}

    def _post_chat(
        self,
        endpoint: str,
        api_key: str,
        payload: dict[str, Any],
        model: str,
        timeout: int = 20,
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if len(detail) > 500:
                detail = detail[:497] + "..."
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            detail = self._format_request_error(exc, endpoint, model)
            raise RuntimeError(f"LLM request failed: {detail}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM response is not valid JSON: {exc}") from exc
        try:
            data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response format is invalid") from exc
        return data

    def _format_request_error(self, exc: BaseException, endpoint: str, model: str) -> str:
        hint = self._network_hint(exc)
        parts = [type(exc).__name__]
        reason = getattr(exc, "reason", None)
        if reason:
            parts.append(f"reason={reason!r}")
        message = str(exc).strip()
        parts.append(message if message else repr(exc))
        if hint:
            parts.append(hint)
        parts.append(f"endpoint={endpoint}")
        parts.append(f"model={model}")
        return "; ".join(parts)

    def _network_hint(self, exc: BaseException) -> str:
        text = f"{exc!r} {getattr(exc, 'reason', '')!r}"
        if "WinError 10013" in text or "PermissionError(13" in text:
            return "网络被当前运行环境拦截：请在本机 PowerShell 直接运行服务，或放行 Python/代理/防火墙"
        if "timed out" in text.lower() or "TimeoutError" in text:
            return "连接超时：请检查网络、代理或接口地址"
        if "NameResolutionError" in text or "getaddrinfo failed" in text:
            return "域名解析失败：请检查 DNS、代理或接口地址"
        return ""

    def _messages(self, task: Task, session: Session, user_text: str) -> list[dict[str, str]]:
        history = [
            {"role": item.role, "content": item.content}
            for item in session.messages[-12:]
            if item.role in {"user", "assistant"}
        ]
        if not history or history[-1] != {"role": "user", "content": user_text}:
            history.append({"role": "user", "content": user_text})
        return [
            {"role": "system", "content": self._system_prompt(task, session)},
            *history,
        ]

    def build_voice_agent_messages(
        self,
        task: Task,
        session: Session,
        user_text: str,
        plan: dict[str, Any],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": self.build_voice_agent_system_prompt(task, plan),
            },
            {
                "role": "user",
                "content": self.build_voice_agent_user_prompt(session, user_text, plan),
            },
        ]

    def build_voice_agent_system_prompt(self, task: Task, plan: dict[str, Any]) -> str:
        exact_text = str(plan.get("exact_text") or "")
        exact_rule = (
            f"本轮 exact_text 不为空，必须原样输出：{exact_text}"
            if exact_text
            else "本轮 exact_text 为空，请只把 required_points 改写成自然电话口语。"
        )
        return "\n".join(
            [
                "# Role",
                task.role,
                "# Task",
                task.task,
                "# Hard Rules",
                "你是电话外呼坐席，不是闲聊助手。",
                "业务流程已经由程序决定，你不能改流程、跳步骤或新增承诺。",
                "只能根据 Next Reply Plan 生成下一句坐席话术。",
                "必须覆盖 required_points，不得添加 plan 外的新业务事实。",
                "不要解释你的推理，不要输出列表，不要输出 JSON。",
                "如果 plan 要求挂断，只输出挂断前最后一句。",
                f"每句长度上限：{plan.get('max_chars')} 个中文字符左右。",
                exact_rule,
                "# Task Constraints",
                "\n".join(f"- {item}" for item in task.constraints),
                "# Knowledge",
                "\n".join(f"- {item}" for item in task.knowledge),
            ]
        )

    def build_voice_agent_user_prompt(
        self,
        session: Session,
        user_text: str,
        plan: dict[str, Any],
    ) -> str:
        transcript = "\n".join(f"{m.role}: {m.content}" for m in session.messages[-10:])
        plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
        variables_json = json.dumps(session.variables, ensure_ascii=False)
        return "\n".join(
            [
                "# Variables",
                variables_json,
                "# Current Transcript",
                transcript,
                "# Latest User Utterance",
                user_text or "(开场，无用户输入)",
                "# Next Reply Plan",
                plan_json,
                "请只输出下一句坐席要说的话。",
            ]
        )

    def _resolve_config(self, session: Session) -> tuple[str, str, str]:
        return self._resolve_values(session.llm_config or {})

    def _resolve_values(self, config: dict[str, str]) -> tuple[str, str, str]:
        global_config = load_llm_config(self.config_path)
        api_key = str(config.get("api_key") or global_config["api_key"]).strip()
        model = str(config.get("model") or global_config["model"]).strip()
        base_url = str(
            config.get("base_url")
            or config.get("api_url")
            or config.get("url")
            or global_config["base_url"]
        ).strip()
        return api_key, model, self._chat_endpoint(base_url)

    def _chat_endpoint(self, base_url: str) -> str:
        url = (base_url or "https://api.openai.com/v1").rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return f"{url}/chat/completions"

    def _system_prompt(self, task: Task, session: Session) -> str:
        transcript = "\n".join(f"{m.role}: {m.content}" for m in session.messages[-8:])
        return "\n".join(
            [
                f"# Role\n{task.role}",
                f"# Task\n{task.task}",
                f"# Response Limit\n{task.response_limit}",
                "# Flow",
                "\n".join(f"- {item}" for item in task.flow),
                "# Knowledge",
                "\n".join(f"- {item}" for item in task.knowledge),
                "# Constraints",
                "\n".join(f"- {item}" for item in task.constraints),
                f"# Variables\n{json.dumps(session.variables, ensure_ascii=False)}",
                "# Current Transcript",
                transcript,
                "只输出下一句外呼坐席回复，不要解释。",
            ]
        )
