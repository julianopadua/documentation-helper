from __future__ import annotations

import asyncio
import random
import time
import re
from dataclasses import dataclass
from typing import Mapping


_DURATION_RE = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?")


def parse_duration_seconds(value: str | None) -> float | None:
    """
    Groq usa strings tipo: '7.66s' ou '2m59.56s'.
    """
    if not value:
        return None
    v = value.strip().lower()
    m = _DURATION_RE.fullmatch(v)
    if not m:
        # fallback: talvez seja um número puro em segundos
        try:
            return float(v)
        except Exception:
            return None
    h = float(m.group(1)) if m.group(1) else 0.0
    mm = float(m.group(2)) if m.group(2) else 0.0
    s = float(m.group(3)) if m.group(3) else 0.0
    out = h * 3600.0 + mm * 60.0 + s
    return out if out > 0 else None


def header_get(headers: Mapping[str, str], key: str) -> str | None:
    # headers podem vir com casing variável
    lk = key.lower()
    for k, v in headers.items():
        if k.lower() == lk:
            return v
    return None


@dataclass
class ThrottleConfig:
    enabled: bool
    min_interval_seconds: float
    min_remaining_tokens: int


class RateLimiter:
    """
    Throttle global simples:
    - Garante um intervalo mínimo entre requests (evita estourar RPM).
    - Se bater 429, espera retry-after/reset-tokens.
    - Se estiver com poucos tokens restantes, espera reset-tokens.
    """

    def __init__(self, cfg: ThrottleConfig) -> None:
        self.cfg = cfg
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0
        self._blocked_until = 0.0

    async def wait_for_slot(self) -> None:
        if not self.cfg.enabled:
            return

        while True:
            async with self._lock:
                now = time.monotonic()
                target = max(self._next_allowed, self._blocked_until)
                wait_s = target - now
                if wait_s <= 0:
                    # reserva o próximo slot
                    self._next_allowed = now + float(self.cfg.min_interval_seconds)
                    return
            await asyncio.sleep(wait_s)

    def on_success_headers(self, headers: Mapping[str, str]) -> None:
        """
        Usa x-ratelimit-remaining-tokens e x-ratelimit-reset-tokens (TPM).
        """
        if not self.cfg.enabled:
            return

        remaining = header_get(headers, "x-ratelimit-remaining-tokens")
        reset = header_get(headers, "x-ratelimit-reset-tokens")

        try:
            remaining_i = int(float(remaining)) if remaining else None
        except Exception:
            remaining_i = None

        reset_s = parse_duration_seconds(reset)

        if remaining_i is not None and reset_s is not None:
            if remaining_i <= int(self.cfg.min_remaining_tokens):
                # espera o reset do TPM com jitter leve
                jitter = 0.2 + random.random() * 0.3
                self._blocked_until = max(self._blocked_until, time.monotonic() + reset_s + jitter)

    def on_rate_limited(self, headers: Mapping[str, str]) -> None:
        """
        Quando vem 429, Groq pode mandar retry-after (segundos) e reset tokens.
        """
        if not self.cfg.enabled:
            return

        ra = header_get(headers, "retry-after")
        reset = header_get(headers, "x-ratelimit-reset-tokens")

        ra_s = parse_duration_seconds(ra)
        reset_s = parse_duration_seconds(reset)

        wait_s = 0.0
        if ra_s:
            wait_s = max(wait_s, ra_s)
        if reset_s:
            wait_s = max(wait_s, reset_s)

        # fallback se não vier nada (raro)
        if wait_s <= 0:
            wait_s = 3.0

        jitter = 0.3 + random.random() * 0.7
        self._blocked_until = max(self._blocked_until, time.monotonic() + wait_s + jitter)
