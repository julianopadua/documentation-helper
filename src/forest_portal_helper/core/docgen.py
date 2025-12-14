# src/forest_portal_helper/core/docgen.py
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from forest_portal_helper.core.chunking import chunk_text_by_lines
from forest_portal_helper.core.config import AppCfg
from forest_portal_helper.core.fs_scanner import iter_source_files, SourceFile
from forest_portal_helper.core.imports_index import build_import_graph
from forest_portal_helper.core.manifest import Manifest, ManifestEntry
from forest_portal_helper.core.output_layout import doc_path_for
from forest_portal_helper.core.prompting import (
    PromptContext,
    load_builtin_template,
    load_file_template,
    render_messages,
)
from forest_portal_helper.core.text_utils import sha256_text, redact_secrets
from forest_portal_helper.core.logging_utils import setup_logging, EventLogger
from forest_portal_helper.llm.groq_client import GroqClient, GroqParams
from forest_portal_helper.llm.rate_limiter import RateLimiter, ThrottleConfig
from forest_portal_helper.llm.router import ModelRouter, RoutingPolicy

log = logging.getLogger("forest_portal_helper.docgen")


@dataclass(frozen=True)
class WorkItem:
    src: SourceFile
    out_path: Path
    rel_key: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kind_from_ext(ext: str) -> str:
    if ext in {".ts", ".tsx", ".js", ".jsx", ".py"}:
        return "code"
    if ext in {".css", ".scss"}:
        return "style"
    if ext == ".json":
        return "json"
    if ext == ".md":
        return "markdown"
    return "unknown"


def _code_fence_from_ext(ext: str) -> str:
    return {
        ".ts": "ts",
        ".tsx": "tsx",
        ".js": "js",
        ".jsx": "jsx",
        ".py": "py",
        ".css": "css",
        ".scss": "scss",
        ".json": "json",
        ".md": "md",
    }.get(ext, "")


def _resolve_defaults(cfg: AppCfg) -> tuple[Path, Path]:
    scan_root = cfg.paths.forest_src
    output_root = cfg.paths.output_root
    return Path(scan_root), Path(output_root)


def _maybe_reset(output_root: Path, state_dir: Path, reset_output: bool, ev: EventLogger) -> None:
    """
    Modo "do zero":
    - remove output_root/generated docs
    - remove state_dir (manifest)
    """
    if not reset_output:
        return

    ev.event("reset_start", output_root=str(output_root), state_dir=str(state_dir))

    if output_root.exists():
        # cuidado: nao deletar o output_root inteiro se ele tiver coisas do usuario
        # aqui removemos apenas a pasta "src" gerada e o INDEX.md, que sao nossos outputs padrao.
        gen_src = output_root / "src"
        index_md = output_root / "INDEX.md"
        if gen_src.exists():
            shutil.rmtree(gen_src, ignore_errors=True)
        if index_md.exists():
            try:
                index_md.unlink()
            except Exception:
                pass

    if state_dir.exists():
        shutil.rmtree(state_dir, ignore_errors=True)

    state_dir.mkdir(parents=True, exist_ok=True)
    ev.event("reset_end")


def _filter_files(
    files: list[SourceFile],
    only_rel_paths: Optional[list[Path]],
) -> list[SourceFile]:
    if not only_rel_paths:
        return files

    wanted = {p.as_posix().lstrip("/").lstrip("\\") for p in only_rel_paths}
    out: list[SourceFile] = []
    for f in files:
        if f.rel_path.as_posix() in wanted:
            out.append(f)
    return out


async def generate_docs(
    cfg: AppCfg,
    force: bool = False,
    scan_root: Optional[Path] = None,
    output_root: Optional[Path] = None,
    include_extensions: Optional[list[str]] = None,
    state_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    reset_output: bool = False,
    only_rel_paths: Optional[list[Path]] = None,
) -> None:
    """
    Gera documentacao.
    - scan_root: pasta que sera documentada (ex: .../forest-portal/src)
    - output_root: pasta onde a documentacao sera salva
    - include_extensions: override do filtro de extensoes
    - state_dir: onde salvar manifest/cache
    - logs_dir: onde salvar logs desta execucao (texto + events)
    - reset_output: modo "do zero"
    - only_rel_paths: processa apenas paths relativos especificos (ex: ["components/Header.tsx"])
    """
    default_scan_root, default_output_root = _resolve_defaults(cfg)
    scan_root = Path(scan_root) if scan_root else default_scan_root
    output_root = Path(output_root) if output_root else default_output_root

    if not scan_root.exists():
        raise FileNotFoundError(f"scan_root nao encontrado: {scan_root}")

    output_root.mkdir(parents=True, exist_ok=True)

    # Se state/logs nao forem informados, usa os do config.
    # No modo interativo, a recomendacao eh manter state/logs dentro do output_root/.fphelper
    state_dir = Path(state_dir) if state_dir else Path(cfg.paths.state_dir)
    logs_dir = Path(logs_dir) if logs_dir else Path(cfg.paths.logs_dir)

    # Configura logging e eventos desta execucao se ainda nao estiver configurado
    # Observacao: se o CLI ja chamou setup_logging, isso vai reconfigurar. Para simplificar rastreio,
    # aceitamos um log por comando. No wizard, logs do docgen ficam no output_root/.fphelper/logs.
    run_id, ev = setup_logging(logs_dir, level=logging.INFO)

    ev.event(
        "run_start",
        scan_root=str(scan_root),
        output_root=str(output_root),
        state_dir=str(state_dir),
        logs_dir=str(logs_dir),
        force=force,
        reset_output=reset_output,
        only_rel_paths=[p.as_posix() for p in only_rel_paths] if only_rel_paths else None,
    )

    _maybe_reset(output_root, state_dir, reset_output, ev)

    # Manifest (cache)
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "manifest.json"
    manifest = Manifest(manifest_path)
    manifest.load()

    # Extensoes
    exts = include_extensions if include_extensions else list(cfg.scan.include_extensions)

    ev.event("scan_config", include_extensions=exts, exclude_dirs=list(cfg.scan.exclude_dirs))

    # Scan
    t_scan0 = time.perf_counter()
    files = list(
        iter_source_files(
            src_root=scan_root,
            include_exts=exts,
            exclude_dirs=cfg.scan.exclude_dirs,
            ignore_patterns=cfg.scan.ignore_patterns,
        )
    )
    files = _filter_files(files, only_rel_paths)
    t_scan1 = time.perf_counter()

    ev.event("scan_done", count=len(files), duration_s=round(t_scan1 - t_scan0, 4))

    if not files:
        ev.event("run_end", ok=True, note="no_files")
        ev.close()
        return

    # Imports graph
    imports_of, imported_by = build_import_graph(
        src_root=scan_root,
        files=files,
        aliases=cfg.resolve.ts_path_aliases,
    )

    # Template
    if cfg.docgen.template_mode == "file":
        if not cfg.docgen.template_file_path:
            raise ValueError("template_mode=file, mas template_file_path esta vazio.")
        template = load_file_template(Path(cfg.docgen.template_file_path))
    else:
        template = load_builtin_template()

    # Groq client
    api_key = (os.environ.get(cfg.llm.api_key_env) or cfg.llm.api_key_fallback or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY ausente. Defina env var ou llm.api_key_fallback.")

    groq = GroqClient(api_key=api_key)

    service_tier = (cfg.llm.service_tier or "").strip()
    if service_tier.lower() in {"", "on_demand"}:
        service_tier_val = None
    else:
        service_tier_val = service_tier

    reasoning_effort = (cfg.llm.reasoning_effort or "").strip() or None

    # stream precisa ser False porque usamos headers do raw response para rate limiting
    params = GroqParams(
        temperature=cfg.llm.temperature,
        top_p=cfg.llm.top_p,
        max_completion_tokens=cfg.llm.max_completion_tokens,
        stream=False,
        service_tier=service_tier_val,
        reasoning_effort=reasoning_effort,
    )

    policy = RoutingPolicy(
        preferred_models=cfg.llm.routing.preferred_models,
        max_attempts_per_model=cfg.llm.retry.max_attempts_per_model,
        backoff_base_s=cfg.llm.retry.backoff_base_seconds,
        backoff_max_s=cfg.llm.retry.backoff_max_seconds,
    )

    th = getattr(cfg.llm, "throttle", None)
    if th is None:
        throttle_cfg = ThrottleConfig(enabled=True, min_interval_seconds=2.2, min_remaining_tokens=800)
    else:
        throttle_cfg = ThrottleConfig(
            enabled=bool(getattr(th, "enabled", True)),
            min_interval_seconds=float(getattr(th, "min_interval_seconds", 2.2)),
            min_remaining_tokens=int(getattr(th, "min_remaining_tokens", 800)),
        )
    limiter = RateLimiter(throttle_cfg)

    router = ModelRouter(groq=groq, policy=policy, params=params, limiter=limiter)

    models = cfg.llm.routing.preferred_models
    if cfg.llm.routing.validate_with_models_endpoint:
        models = await router.validate_models()

    ev.event("models_ready", models=models)

    # Work items
    work: list[WorkItem] = []
    for f in files:
        out_path = doc_path_for(f.rel_path, output_root, cfg.docgen.output_layout)
        work.append(WorkItem(src=f, out_path=out_path, rel_key=f.rel_path.as_posix()))

    # Concurrency
    sem = asyncio.Semaphore(cfg.performance.max_concurrency)

    async def process_one(w: WorkItem) -> None:
        async with sem:
            t0 = time.perf_counter()
            raw = w.src.abs_path.read_text(encoding="utf-8", errors="ignore")
            raw = redact_secrets(raw)
            sha = sha256_text(raw)

            ev.event(
                "file_seen",
                rel_path=w.rel_key,
                abs_path=str(w.src.abs_path),
                out_path=str(w.out_path),
                size_bytes=len(raw.encode("utf-8", errors="ignore")),
            )

            if (not force) and manifest.get_sha(w.rel_key) == sha and w.out_path.exists():
                ev.event("file_skipped_cache", rel_path=w.rel_key)
                return

            chunks = chunk_text_by_lines(
                raw,
                max_chars=cfg.docgen.max_chars_per_request,
                overlap_lines=cfg.docgen.chunk_overlap_lines,
            )

            ev.event("file_start", rel_path=w.rel_key, chunks=len(chunks))

            partial_docs: list[str] = []
            used_models: list[str] = []

            for i, chunk in enumerate(chunks, start=1):
                rel_path = w.src.rel_path
                kind = _kind_from_ext(w.src.ext)
                fence = _code_fence_from_ext(w.src.ext)

                imports_links: list[tuple[Path, Path]] = []
                for e in imports_of.get(rel_path, []):
                    doc_rel = doc_path_for(e.target, output_root, cfg.docgen.output_layout).relative_to(output_root)
                    imports_links.append((e.target, doc_rel))

                imported_by_links: list[tuple[Path, Path]] = []
                for e in imported_by.get(rel_path, []):
                    doc_rel = doc_path_for(e.src, output_root, cfg.docgen.output_layout).relative_to(output_root)
                    imported_by_links.append((e.src, doc_rel))

                ctx = PromptContext(
                    rel_path=rel_path,
                    file_kind=f"{kind} (chunk {i}/{len(chunks)})" if len(chunks) > 1 else kind,
                    code_fence=fence,
                    code=chunk,
                    imports_links=imports_links,
                    imported_by_links=imported_by_links,
                )

                messages = render_messages(
                    template=template,
                    ctx=ctx,
                    language=cfg.docgen.language,
                    tone=cfg.docgen.tone,
                    snippet_max_lines_per_block=cfg.docgen.snippet_max_lines_per_block,
                    max_snippet_blocks=cfg.docgen.max_snippet_blocks,
                )

                ev.event("chunk_start", rel_path=w.rel_key, chunk=i, chunk_total=len(chunks))

                t_chunk0 = time.perf_counter()
                doc_txt, used_model = await router.generate(messages=messages, models=models)
                t_chunk1 = time.perf_counter()

                ev.event(
                    "chunk_end",
                    rel_path=w.rel_key,
                    chunk=i,
                    chunk_total=len(chunks),
                    used_model=used_model,
                    duration_s=round(t_chunk1 - t_chunk0, 4),
                    out_chars=len(doc_txt),
                )

                partial_docs.append(doc_txt.strip())
                used_models.append(used_model)

            final_doc = partial_docs[0]
            used_model_final = used_models[0] if used_models else "unknown"

            if len(partial_docs) > 1:
                merge_messages = [
                    {
                        "role": "user",
                        "content": (
                            "Unifique as documentacoes parciais (chunks) abaixo em um unico Markdown coerente. "
                            "Remova duplicacoes, mantenha a ordem, preserve todos os pontos relevantes. "
                            "Nao invente nada.\n\n" + "\n\n---\n\n".join(partial_docs)
                        ),
                    }
                ]

                ev.event("merge_start", rel_path=w.rel_key, parts=len(partial_docs))
                t_merge0 = time.perf_counter()
                final_doc, used_model_final = await router.generate(messages=merge_messages, models=models)
                t_merge1 = time.perf_counter()
                ev.event(
                    "merge_end",
                    rel_path=w.rel_key,
                    used_model=used_model_final,
                    duration_s=round(t_merge1 - t_merge0, 4),
                    out_chars=len(final_doc),
                )

            w.out_path.parent.mkdir(parents=True, exist_ok=True)
            w.out_path.write_text(final_doc.strip() + "\n", encoding="utf-8")

            manifest.set_entry(
                w.rel_key,
                ManifestEntry(
                    sha256=sha,
                    model=used_model_final,
                    updated_at=_utc_now_iso(),
                ),
            )

            t1 = time.perf_counter()
            ev.event(
                "file_end",
                rel_path=w.rel_key,
                out_path=str(w.out_path),
                used_model=used_model_final,
                duration_s=round(t1 - t0, 4),
            )

    t_run0 = time.perf_counter()
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("Gerando docs...", total=len(work))
            for fut in asyncio.as_completed([process_one(w) for w in work]):
                await fut
                progress.advance(task)

        manifest.save()

        if cfg.docgen.write_project_index:
            await _write_index(output_root, work, ev)

        t_run1 = time.perf_counter()
        ev.event("run_end", ok=True, duration_s=round(t_run1 - t_run0, 4))
    except Exception as e:
        t_run1 = time.perf_counter()
        ev.event("run_end", ok=False, duration_s=round(t_run1 - t_run0, 4), error=str(e))
        raise
    finally:
        try:
            await groq.close()
        except Exception:
            pass
        ev.close()


async def _write_index(output_root: Path, work: list[WorkItem], ev: EventLogger) -> None:
    index_path = output_root / "INDEX.md"

    lines: list[str] = []
    lines.append("# Indice de documentacao\n")
    lines.append("Gerado automaticamente pelo forest-portal-helper.\n")

    for w in sorted(work, key=lambda x: x.rel_key):
        doc_rel = w.out_path.relative_to(output_root).as_posix()
        lines.append(f"- {w.rel_key} -> [{doc_rel}]({doc_rel})")

    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ev.event("index_written", path=str(index_path), entries=len(work))
