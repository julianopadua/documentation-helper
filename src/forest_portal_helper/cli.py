from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
import typer

from forest_portal_helper.core.config import load_config
from forest_portal_helper.core.docgen import generate_docs
from forest_portal_helper.core.logging_utils import setup_logging

app = typer.Typer(add_completion=False)


@app.command()
def build(
    config: Path = typer.Option(Path("config.yaml"), "--config", exists=True),
    force: bool = typer.Option(False, "--force", help="Ignora cache/manifest e reprocessa tudo."),
) -> None:
    cfg = load_config(config)
    setup_logging(cfg.paths.logs_dir, level=logging.INFO)
    asyncio.run(generate_docs(cfg, force=force))


@app.command()
def models(
    config: Path = typer.Option(Path("config.yaml"), "--config", exists=True),
) -> None:
    cfg = load_config(config)
    api_key = (os.environ.get(cfg.llm.api_key_env) or cfg.llm.api_key_fallback or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY ausente (env var ou llm.api_key_fallback).")

    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    r = httpx.get(url, headers=headers, timeout=30.0)
    r.raise_for_status()

    data = r.json().get("data", [])
    ids = sorted([m.get("id") for m in data if m.get("id")])
    for mid in ids:
        typer.echo(mid)
