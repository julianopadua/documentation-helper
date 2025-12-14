# src/forest_portal_helper/llm/router.py
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, replace
from typing import Mapping

from groq import APIStatusError, RateLimitError

from forest_portal_helper.llm.groq_client import GroqClient, GroqParams
from forest_portal_helper.llm.rate_limiter import RateLimiter

log = logging.getLogger("forest_portal_helper.router")


@dataclass(frozen=True)
class RoutingPolicy:
    preferred_models: list[str]
    max_attempts_per_model: int
    backoff_base_s: float
    backoff_max_s: float


def _safe_error_info(e: APIStatusError) -> tuple[str, str]:
    try:
        body = e.response.json()
        err = body.get("error", {}) if isinstance(body, dict) else {}
        return str(err.get("type", "")), str(err.get("message", ""))
    except Exception:
        return "", str(e)


class ModelRouter:
    def __init__(
        self,
        groq: GroqClient,
        policy: RoutingPolicy,
        params: GroqParams,
        limiter: RateLimiter,
    ) -> None:
        self.groq = groq
        self.policy = policy
        self.params = params
        self.limiter = limiter

        self._forced_service_tier: str | None = None
        self._disabled_models: set[str] = set()

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
            if model in self._disabled_models:
                continue

            for attempt in range(1, self.policy.max_attempts_per_model + 1):
                eff_params = self.params
                if self._forced_service_tier:
                    eff_params = replace(eff_params, service_tier=self._forced_service_tier)

                try:
                    await self.limiter.wait_for_slot()
                    txt, headers = await self.groq.chat_raw(model=model, messages=messages, params=eff_params)
                    self.limiter.on_success_headers(headers)
                    return txt, model

                except RateLimitError as e:
                    last_err = e
                    hdrs: Mapping[str, str] = {}
                    try:
                        if getattr(e, "response", None) is not None:
                            hdrs = e.response.headers
                    except Exception:
                        hdrs = {}
                    self.limiter.on_rate_limited(hdrs)
                    log.warning("429 no modelo=%s attempt=%s; aguardando janela de rate limit.", model, attempt)
                    continue

                except APIStatusError as e:
                    last_err = e
                    status = getattr(e.response, "status_code", None)
                    etype, emsg = _safe_error_info(e)

                    # 429 via APIStatusError também
                    if status == 429:
                        self.limiter.on_rate_limited(e.response.headers)
                        log.warning("429 no modelo=%s attempt=%s; aguardando janela de rate limit.", model, attempt)
                        continue

                    # service_tier não permitido (plano free) -> força on_demand e tenta novamente
                    if status == 400 and "service_tier" in emsg and "not available for this org" in emsg:
                        log.warning("service_tier inválido para sua org. Forçando on_demand e repetindo.")
                        self._forced_service_tier = "on_demand"
                        await asyncio.sleep(0.2)
                        continue

                    # flex capacity_exceeded (se acontecer) -> rebaixa para on_demand e tenta novamente
                    if status == 498 and "capacity_exceeded" in emsg.lower():
                        log.warning("capacity_exceeded (provável flex). Forçando on_demand e repetindo.")
                        self._forced_service_tier = "on_demand"
                        await asyncio.sleep(0.2)
                        continue

                    if status and int(status) >= 500:
                        sleep_s = self._jitter_backoff(attempt)
                        log.warning("5xx=%s no modelo=%s; dormindo %.2fs", status, model, sleep_s)
                        await asyncio.sleep(sleep_s)
                        continue

                    # 4xx estrutural: desabilita modelo nesta execução
                    if status and int(status) in {400, 404, 422}:
                        log.warning(
                            "4xx estrutural no modelo=%s (status=%s type=%s). Desabilitando. msg=%s",
                            model,
                            status,
                            etype,
                            emsg,
                        )
                        self._disabled_models.add(model)
                        break

                    log.warning("Erro status=%s no modelo=%s. Próximo modelo. msg=%s", status, model, emsg)
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
