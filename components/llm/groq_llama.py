from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Sequence

import httpx
from stageflow import StageContext, StageKind, StageOutput
from stageflow.helpers import LLMResponse

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

StreamCallback = Callable[[str, str], Awaitable[None] | None]


def _coerce_messages(messages: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    coerced: List[Dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not role or not content:
            continue
        coerced.append({"role": role, "content": content})
    if not coerced:
        raise ValueError("GroqLLMClient requires at least one populated message")
    return coerced


def _maybe_await(result: Awaitable[None] | None) -> Awaitable[None]:
    if result is None:
        return asyncio.sleep(0)
    if asyncio.iscoroutine(result):
        return result  # type: ignore[return-value]
    return asyncio.sleep(0)


@dataclass(slots=True)
class GroqChatSettings:
    """Runtime settings for Groq chat completions."""

    model: str = "llama-3.1-8b-instant"
    temperature: float = 0.2
    top_p: float = 0.95
    max_tokens: int = 1024
    stream: bool = True
    user: str | None = None


class GroqLLMClient:
    """Minimal Groq chat client with optional streaming callbacks."""

    def __init__(
        self,
        api_key: str | None = None,
        settings: GroqChatSettings | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.settings = settings or GroqChatSettings()
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "GROQ_API_KEY is required to use GroqLLMClient (set env var or pass api_key)."
            )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: Sequence[Dict[str, str]],
        *,
        metadata: Dict[str, Any] | None = None,
        on_stream_chunk: StreamCallback | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self.settings.model,
            "messages": _coerce_messages(messages),
            "temperature": temperature if temperature is not None else self.settings.temperature,
            "top_p": self.settings.top_p,
            "max_tokens": max_tokens if max_tokens is not None else self.settings.max_tokens,
            "stream": stream if stream is not None else self.settings.stream,
        }
        if metadata:
            payload["metadata"] = metadata
        if self.settings.user:
            payload["user"] = self.settings.user

        if payload["stream"] and on_stream_chunk:
            content = await self._streaming_chat(payload, on_stream_chunk)
        else:
            content = await self._non_streaming_chat(payload)

        return LLMResponse(
            content=content,
            provider="groq",
            model=payload["model"],
            input_tokens=sum(len(m["content"]) for m in payload["messages"]),
            output_tokens=len(content),
        )

    async def _non_streaming_chat(self, payload: Dict[str, Any]) -> str:
        response = await self._client.post(GROQ_CHAT_COMPLETIONS_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _streaming_chat(
        self,
        payload: Dict[str, Any],
        on_chunk: StreamCallback,
    ) -> str:
        content = ""
        async with self._client.stream("POST", GROQ_CHAT_COMPLETIONS_URL, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                data = json.loads(chunk)
                delta = data["choices"][0]["delta"].get("content") or ""
                if not delta:
                    continue
                content += delta
                await _maybe_await(on_chunk(delta, content))
        return content


def build_route_system_prompt(route: str, profile: Dict[str, Any], memory: Dict[str, Any]) -> str:
    """Default prompt builder that personalizes instructions per route."""

    parts = [
        "You are Stageflow's reliability agent responsible for stress-testing pipelines.",
        f"Route context: {route}.",
    ]
    if profile:
        display_name = profile.get("display_name")
        if display_name:
            parts.append(f"Working on behalf of {display_name}.")
        goals = profile.get("goals")
        if goals:
            parts.append("Goals: " + ", ".join(goals[:3]))
    if memory.get("recent_topics"):
        parts.append("Recent topics: " + ", ".join(memory["recent_topics"][:3]))
    parts.append("Follow Stageflow testing doctrine. Be explicit about failure modes and mitigations.")
    return " ".join(parts)


class GroqChatStage:
    """Stageflow stage that routes work through the Groq Llama 3 8B model."""

    name = "groq_llm"
    kind = StageKind.TRANSFORM

    def __init__(
        self,
        client: GroqLLMClient | None = None,
        *,
        system_prompt_builder: Callable[[str, Dict[str, Any], Dict[str, Any]], str] = build_route_system_prompt,
    ) -> None:
        self._client = client or GroqLLMClient()
        self._system_prompt_builder = system_prompt_builder

    async def execute(self, ctx: StageContext) -> StageOutput:
        snapshot = ctx.snapshot
        route = ctx.inputs.get("route", "general")
        profile = ctx.inputs.get("profile", {})
        memory = ctx.inputs.get("memory", {})
        system_prompt = self._system_prompt_builder(route, profile, memory)

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if snapshot.messages:
            for msg in snapshot.messages[-10:]:
                messages.append({"role": msg.role, "content": msg.content})
        if snapshot.input_text:
            messages.append({"role": "user", "content": snapshot.input_text})

        async def stream_hook(delta: str, accumulated: str) -> None:
            ctx.emit_event(
                "llm.token",
                {
                    "delta": delta,
                    "partial": accumulated,
                    "stage": self.name,
                },
            )

        llm_response = await self._client.chat(
            messages,
            on_stream_chunk=stream_hook,
        )

        return StageOutput.ok(
            response=llm_response.content,
            route=route,
            llm=llm_response.to_dict(),
        )
