from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from groq import AsyncGroq
from groq import APIStatusError


@dataclass(frozen=True)
class GroqParams:
    temperature: float
    top_p: float
    max_completion_tokens: int
    stream: bool
    service_tier: str | None
    reasoning_effort: str | None


def _effective_reasoning_effort(model: str, requested: str | None) -> str | None:
    """
    Groq docs:
    - GPT-OSS 20B/120B: low|medium|high
    - Qwen3-32B: none|default
    Outros modelos: não suportam -> não enviar o parâmetro.
    :contentReference[oaicite:3]{index=3}
    """
    if not requested:
        return None

    m = model.strip()

    if m in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        if requested in {"low", "medium", "high"}:
            return requested
        # se vier "default", mapeia pra medium
        if requested == "default":
            return "medium"
        return None

    if m in {"qwen/qwen3-32b"}:
        if requested in {"none", "default"}:
            return requested
        # se usuário configurou low/medium/high, converte pra "default"
        if requested in {"low", "medium", "high"}:
            return "default"
        return None

    return None


class GroqClient:
    def __init__(self, api_key: str, timeout_s: float = 90.0) -> None:
        self._api_key = api_key
        self._client = AsyncGroq(api_key=api_key, timeout=timeout_s)

    async def close(self) -> None:
        await self._client.close()

    async def list_models(self) -> set[str]:
        url = "https://api.groq.com/openai/v1/models"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(url, headers=headers)
            r.raise_for_status()
            data = r.json().get("data", [])
            return {m.get("id") for m in data if m.get("id")}

    async def chat(self, model: str, messages: list[dict[str, str]], params: GroqParams) -> str:
        eff_reason = _effective_reasoning_effort(model, params.reasoning_effort)

        # Monta kwargs de forma segura (omitir params que quebram em certos modelos/planos).
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_completion_tokens": params.max_completion_tokens,
            "stream": params.stream,
        }

        # service_tier default é on_demand quando omitido. :contentReference[oaicite:4]{index=4}
        if params.service_tier:
            kwargs["service_tier"] = params.service_tier

        if eff_reason:
            kwargs["reasoning_effort"] = eff_reason

        if not params.stream:
            resp = await self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

        chunks: list[str] = []
        stream = await self._client.chat.completions.create(**kwargs)
        async for part in stream:
            delta = part.choices[0].delta.content or ""
            if delta:
                chunks.append(delta)
        return "".join(chunks)


def parse_retry_after_seconds(e: APIStatusError) -> float | None:
    try:
        hdr = e.response.headers.get("retry-after")
        if not hdr:
            return None
        return float(hdr)
    except Exception:
        return None
