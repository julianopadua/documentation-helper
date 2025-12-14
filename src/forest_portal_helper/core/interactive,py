# src/forest_portal_helper/core/interactive.py
from __future__ import annotations

import logging
from pathlib import Path

import typer

from forest_portal_helper.core.docgen import generate_docs

log = logging.getLogger("forest_portal_helper.interactive")


def _parse_exts(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[str] = []
    for p in parts:
        if not p.startswith("."):
            p = "." + p
        out.append(p.lower())
    # remove duplicadas preservando ordem
    seen: set[str] = set()
    dedup: list[str] = []
    for e in out:
        if e not in seen:
            seen.add(e)
            dedup.append(e)
    return dedup


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _default_exts_from_cfg(cfg) -> str:
    try:
        exts = list(getattr(cfg.scan, "include_extensions", []))
        if exts:
            return ",".join(exts)
    except Exception:
        pass
    return ".ts,.tsx,.js,.jsx,.css,.scss,.json,.md"


def run_wizard(cfg) -> None:
    """
    Sessao interativa.
    Pergunta paths e extensoes, roda docgen, e oferece loop para rodar de novo.
    """
    typer.echo("")
    typer.echo("Forest Portal Helper - Modo interativo")
    typer.echo("")

    default_scan_root = None
    try:
        default_scan_root = Path(cfg.paths.forest_src)
    except Exception:
        default_scan_root = None

    while True:
        typer.echo("")
        typer.echo("Configurar execucao")
        typer.echo("")

        scan_root_str = typer.prompt(
            "Pasta fonte a documentar (scan_root)",
            default=str(default_scan_root) if default_scan_root else "",
        ).strip()
        scan_root = Path(scan_root_str)

        if not scan_root.exists() or not scan_root.is_dir():
            typer.echo("Erro: scan_root nao existe ou nao eh pasta. Tente novamente.")
            continue

        output_root_str = typer.prompt(
            "Pasta destino para salvar a documentacao (output_root)",
            default=str(getattr(cfg.paths, "output_root", Path.cwd() / "generated")),
        ).strip()
        output_root = Path(output_root_str)
        _ensure_dir(output_root)

        # State e logs ficam junto do output_root para facilitar "continuar" e auditoria
        state_dir = output_root / ".fphelper" / "state"
        logs_dir = output_root / ".fphelper" / "logs"
        _ensure_dir(state_dir)
        _ensure_dir(logs_dir)

        exts_default = _default_exts_from_cfg(cfg)
        exts_raw = typer.prompt(
            "Extensoes (separe por virgula). Ex: .tsx,.ts,.css",
            default=exts_default,
        ).strip()
        include_exts = _parse_exts(exts_raw)

        if not include_exts:
            typer.echo("Erro: nenhuma extensao informada.")
            continue

        mode = typer.prompt(
            "Modo (1 = continuar, 2 = do zero)",
            default="1",
        ).strip()

        reset_output = mode == "2"
        if reset_output:
            typer.echo("Modo do zero selecionado: output e manifest serao reiniciados.")
        else:
            typer.echo("Modo continuar selecionado: manifest e output serao reaproveitados.")

        force = typer.confirm("Forcar regeneracao mesmo se o arquivo nao mudou", default=False)

        typer.echo("")
        typer.echo("Executando...")
        typer.echo("")

        try:
            # Importante: generate_docs ja faz logging de eventos por arquivo e por chunk
            # e respeita rate limiting via router/limiter.
            import asyncio
            asyncio.run(
                generate_docs(
                    cfg=cfg,
                    force=force,
                    scan_root=scan_root,
                    output_root=output_root,
                    include_extensions=include_exts,
                    state_dir=state_dir,
                    logs_dir=logs_dir,
                    reset_output=reset_output,
                    only_rel_paths=None,
                )
            )
            typer.echo("")
            typer.echo("Execucao finalizada.")
        except Exception as e:
            typer.echo("")
            typer.echo(f"Falha: {e}")

        typer.echo("")
        if not typer.confirm("Deseja documentar mais arquivos (mesmo ou outro projeto)", default=False):
            typer.echo("Encerrando modo interativo.")
            return
