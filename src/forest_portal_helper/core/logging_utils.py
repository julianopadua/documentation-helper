# src/forest_portal_helper/core/logging_utils.py
from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rnd = secrets.token_hex(3)
    return f"{ts}_{rnd}"


@dataclass
class EventLogger:
    """
    Logger de eventos estruturados (JSONL).
    Cada linha eh um evento com timestamp, run_id e campos adicionais.

    Uso:
      ev.event("file_start", rel_path="src/x.tsx", out_path="...", size_bytes=1234)
    """

    path: Path
    run_id: str

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def event(self, name: str, **fields: Any) -> None:
        payload = {
            "ts_utc": _utc_now_iso(),
            "run_id": self.run_id,
            "event": name,
            **fields,
        }
        self._fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> tuple[str, EventLogger]:
    """
    Configura logging de texto + logger de eventos JSONL.

    Saidas:
      logs/run_<run_id>.log
      logs/events_<run_id>.jsonl
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = _make_run_id()

    text_log_path = logs_dir / f"run_{run_id}.log"
    events_path = logs_dir / f"events_{run_id}.jsonl"

    root = logging.getLogger()
    root.setLevel(level)

    # Evita duplicar handlers se o usuario rodar varias vezes na mesma sessao
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")

    fh = logging.FileHandler(text_log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    ev = EventLogger(path=events_path, run_id=run_id)

    logging.getLogger("forest_portal_helper").info("run_id=%s", run_id)
    logging.getLogger("forest_portal_helper").info("text_log=%s", str(text_log_path))
    logging.getLogger("forest_portal_helper").info("events_log=%s", str(events_path))

    # Loga ambiente basico
    logging.getLogger("forest_portal_helper").info("cwd=%s", os.getcwd())
    logging.getLogger("forest_portal_helper").info("pid=%s", os.getpid())

    ev.event(
        "run_boot",
        text_log=str(text_log_path),
        events_log=str(events_path),
        cwd=os.getcwd(),
        pid=os.getpid(),
    )
    return run_id, ev
