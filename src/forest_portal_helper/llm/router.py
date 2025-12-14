from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from groq import APIStatusError

from forest_portal_helper.llm.groq_client import GroqClient, GroqParams, parse_retry_after_seconds

log = logging.getLogger("forest_portal_helper.router")


@dataclass(frozen=True)
class RoutingPolicy:
    preferred_models: list[str]
    max_attempts_per_model: int
    backoff_base_s: float
    backoff_max_s: float


class ModelRouter:
    def __init__(self, groq: GroqClient, policy: RoutingPolicy, params: GroqParams) -> None:
        self.groq = groq
        self.policy = policy
        self.params = params

    async def validate_models(self) -> list[str]:
        available = await self.groq.list_models()
        models = [m for m in self.policy.preferred_models if m in available]
        missing = [m for m in self.policy.preferred_models if m not in available]
        if missing:
            log.warning("Modelos ausentes (ignorando): %s", missing)
        if not models:
            raise RuntimeError("Nenhum modelo preferido está disponível em /models.")
        return models

    async def generate(self, messages: list[dict[str, str]], models: list[str]) -> tuple[str, str]:
        last_err: Exception | None = None

        for model in models:
            for attempt in range(1, self.policy.max_attempts_per_model + 1):
                try:
                    txt = await self.groq.chat(model=model, messages=messages, params=self.params)
                    return txt, model

                except APIStatusError as e:
                    last_err = e
                    status = getattr(e.response, "status_code", None)

                    if status == 429:
                        ra = parse_retry_after_seconds(e)
                        sleep_s = ra if ra is not None else self._jitter_backoff(attempt)
                        log.warning("429 no modelo=%s attempt=%s; dormindo %.2fs", model, attempt, sleep_s)
                        await asyncio.sleep(sleep_s)
                        continue

                    if status and int(status) >= 500:
                        sleep_s = self._jitter_backoff(attempt)
                        log.warning("5xx=%s no modelo=%s attempt=%s; dormindo %.2fs", status, model, attempt, sleep_s)
                        await asyncio.sleep(sleep_s)
                        continue

                    log.warning("Erro status=%s no modelo=%s (attempt=%s). Próximo modelo.", status, model, attempt)
                    break

                except Exception as e:
                    last_err = e
                    log.warning("Erro inesperado no modelo=%s attempt=%s: %s", model, attempt, e)
                    break

        raise RuntimeError(f"Falha ao gerar após tentar todos os modelos. Último erro: {last_err}")

    def _jitter_backoff(self, attempt: int) -> float:
        base = self.policy.backoff_base_s * (2 ** (attempt - 1))
        base = min(base, self.policy.backoff_max_s)
        return base * (0.7 + random.random() * 0.6)
