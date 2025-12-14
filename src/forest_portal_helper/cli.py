# src/forest_portal_helper/cli.py
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer

from forest_portal_helper.core.config import load_config
from forest_portal_helper.core.docgen import generate_docs
from forest_portal_helper.core.interactive import run_wizard
from forest_portal_helper.core.logging_utils import setup_logging

app = typer.Typer(add_completion=False)
log = logging.getLogger("forest_portal_helper.cli")


@app.command()
def build(
    config: Path = typer.Option(Path("config.yaml"), "--config", exists=True),
    force: bool = typer.Option(False, "--force", help="Ignora cache/manifest e reprocessa tudo."),
) -> None:
    """
    Execucao nao interativa, usando config.yaml como base.
    """
    cfg = load_config(config)

    run_id, ev = setup_logging(cfg.paths.logs_dir, level=logging.INFO)
    ev.event("cmd_build_start", config=str(config), force=force)

    try:
        asyncio.run(
            generate_docs(
                cfg=cfg,
                force=force,
                scan_root=None,
                output_root=None,
                include_extensions=None,
                state_dir=None,
                logs_dir=None,
                reset_output=False,
                only_rel_paths=None,
            )
        )
        ev.event("cmd_build_end", ok=True)
    except Exception as e:
        ev.event("cmd_build_end", ok=False, error=str(e))
        raise
    finally:
        ev.close()


@app.command()
def wizard(
    config: Path = typer.Option(Path("config.yaml"), "--config", exists=True),
) -> None:
    """
    Modo interativo.
    Usuario escolhe scan_root, output_root, extensoes e modo (continuar ou do zero).
    """
    cfg = load_config(config)

    # No wizard, logs vao para output_root/.fphelper/logs, configurado dentro do wizard.
    # Mesmo assim criamos um log "fallback" no cfg.paths.logs_dir para capturar erros precoces.
    run_id, ev = setup_logging(cfg.paths.logs_dir, level=logging.INFO)
    ev.event("cmd_wizard_start", config=str(config))

    try:
        run_wizard(cfg)
        ev.event("cmd_wizard_end", ok=True)
    except Exception as e:
        ev.event("cmd_wizard_end", ok=False, error=str(e))
        raise
    finally:
        ev.close()


@app.command()
def file(
    rel_path: str = typer.Argument(..., help="Caminho relativo ao scan_root (ex: components/Header.tsx)"),
    config: Path = typer.Option(Path("config.yaml"), "--config", exists=True),
    force: bool = typer.Option(False, "--force"),
    scan_root: Optional[Path] = typer.Option(None, "--scan-root", help="Pasta base a documentar. Default vem do config."),
    output_root: Optional[Path] = typer.Option(None, "--output-root", help="Pasta destino. Default vem do config."),
) -> None:
    """
    Documenta apenas um arquivo (por caminho relativo).
    """
    cfg = load_config(config)

    run_id, ev = setup_logging(cfg.paths.logs_dir, level=logging.INFO)
    ev.event("cmd_file_start", config=str(config), force=force, rel_path=rel_path)

    try:
        asyncio.run(
            generate_docs(
                cfg=cfg,
                force=force,
                scan_root=scan_root,
                output_root=output_root,
                include_extensions=None,
                state_dir=None,
                logs_dir=None,
                reset_output=False,
                only_rel_paths=[Path(rel_path)],
            )
        )
        ev.event("cmd_file_end", ok=True)
    except Exception as e:
        ev.event("cmd_file_end", ok=False, error=str(e))
        raise
    finally:
        ev.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
