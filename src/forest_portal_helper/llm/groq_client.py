# src/forest_portal_helper/llm/groq_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from groq import AsyncGroq


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
    Aplica reasoning_effort só quando fizer sentido.

    - openai/gpt-oss-20b | openai/gpt-oss-120b: low|medium|high
    - qwen/qwen3-32b: none|default
    - demais modelos: não enviar reasoning_effort
    """
    if not requested:
        return None

    m = model.strip()

    if m in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        if requested in {"low", "medium", "high"}:
            return requested
        if requested == "default":
            return "medium"
        return None

    if m in {"qwen/qwen3-32b"}:
        if requested in {"none", "default"}:
            return requested
        if requested in {"low", "medium", "high"}:
            return "default"
        return None

    return None


class GroqClient:
    def __init__(self, api_key: str, timeout_s: float = 90.0) -> None:
        self._client = AsyncGroq(
            api_key=api_key,
            timeout=timeout_s,
            max_retries=0,  # controle de retry fica no router + rate limiter
        )

    async def close(self) -> None:
        await self._client.close()

    async def list_models(self) -> set[str]:
        resp = await self._client.models.list()
        return {m.id for m in resp.data if getattr(m, "id", None)}

    async def chat_raw(
        self,
        model: str,
        messages: list[dict[str, str]],
        params: GroqParams,
    ) -> tuple[str, Mapping[str, str]]:
        """
        Faz uma chamada de chat e retorna (texto, headers).
        Usamos raw response para conseguir ler headers de rate limit.
        """
        if params.stream:
            raise RuntimeError("stream=True não suportado com chat_raw (precisamos de headers).")

        eff_reason = _effective_reasoning_effort(model, params.reasoning_effort)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_completion_tokens": params.max_completion_tokens,
            "stream": False,
        }

        # on_demand é default quando omitido; então só enviamos se vier algo diferente de None.
        if params.service_tier:
            kwargs["service_tier"] = params.service_tier

        if eff_reason:
            kwargs["reasoning_effort"] = eff_reason

        raw = await self._client.chat.completions.with_raw_response.create(**kwargs)
        headers = raw.headers
        completion = await raw.parse()

        text = completion.choices[0].message.content or ""
        return text, headers
