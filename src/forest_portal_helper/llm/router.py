from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, replace

from groq import APIStatusError

from forest_portal_helper.llm.groq_client import GroqClient, GroqParams, parse_retry_after_seconds

log = logging.getLogger("forest_portal_helper.router")


@dataclass(frozen=True)
class RoutingPolicy:
    preferred_models: list[str]
    max_attempts_per_model: int
    backoff_base_s: float
    backoff_max_s: float


def _safe_error_info(e: APIStatusError) -> tuple[str, str]:
    """
    Retorna (type, message) tentando ler o JSON padrão do OpenAI-compatible.
    """
    try:
        body = e.response.json()
        err = body.get("error", {}) if isinstance(body, dict) else {}
        return str(err.get("type", "")), str(err.get("message", ""))
    except Exception:
        return "", str(e)


class ModelRouter:
    def __init__(self, groq: GroqClient, policy: RoutingPolicy, params: GroqParams) -> None:
        self.groq = groq
        self.policy = policy
        self.params = params

        # Se sua org não aceita auto/flex, a gente rebaixa e mantém aqui.
        self._forced_service_tier: str | None = None

        # Modelos que deram erro 4xx “estrutural” (incompatível) nesta execução.
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
                # aplica “forced service tier” se detectarmos que sua org não suporta auto/flex
                eff_params = self.params
                if self._forced_service_tier:
                    eff_params = replace(eff_params, service_tier=self._forced_service_tier)

                try:
                    txt = await self.groq.chat(model=model, messages=messages, params=eff_params)
                    return txt, model

                except APIStatusError as e:
                    last_err = e
                    status = getattr(e.response, "status_code", None)
                    etype, emsg = _safe_error_info(e)

                    # 429: respeitar retry-after se existir
                    if status == 429:
                        ra = parse_retry_after_seconds(e)
                        sleep_s = ra if ra is not None else self._jitter_backoff(attempt)
                        log.warning("429 no modelo=%s attempt=%s; dormindo %.2fs", model, attempt, sleep_s)
                        await asyncio.sleep(sleep_s)
                        continue

                    # flex pode falhar rápido com 498 capacity_exceeded. Rebaixa pra on_demand. :contentReference[oaicite:5]{index=5}
                    if status == 498 and "capacity_exceeded" in emsg.lower():
                        log.warning("498 capacity_exceeded (provável flex). Rebaixando para on_demand e repetindo.")
                        self._forced_service_tier = "on_demand"
                        await asyncio.sleep(0.2)
                        continue

                    # Seu caso: 400 dizendo que service_tier=auto não é permitido.
                    if status == 400 and "service_tier" in emsg and "not available for this org" in emsg:
                        log.warning("service_tier inválido pra sua org. Forçando on_demand e repetindo.")
                        self._forced_service_tier = "on_demand"
                        await asyncio.sleep(0.2)
                        continue

                    # 5xx: backoff e tenta de novo
                    if status and int(status) >= 500:
                        sleep_s = self._jitter_backoff(attempt)
                        log.warning("5xx=%s no modelo=%s attempt=%s; dormindo %.2fs", status, model, attempt, sleep_s)
                        await asyncio.sleep(sleep_s)
                        continue

                    # 4xx “estrutural”: marca modelo como não utilizável nesta execução e cai pro próximo
                    if status and int(status) in {400, 404, 422}:
                        log.warning(
                            "4xx estrutural no modelo=%s (status=%s type=%s). Desabilitando este modelo nesta execução. msg=%s",
                            model, status, etype, emsg
                        )
                        self._disabled_models.add(model)
                        break

                    # default: cai pro próximo modelo
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
