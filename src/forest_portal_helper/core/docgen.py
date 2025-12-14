from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
from forest_portal_helper.llm.groq_client import GroqClient, GroqParams
from forest_portal_helper.llm.router import ModelRouter, RoutingPolicy

log = logging.getLogger("forest_portal_helper.docgen")


@dataclass(frozen=True)
class WorkItem:
    src: SourceFile
    out_path: Path
    rel_key: str


def _kind_from_ext(ext: str) -> str:
    if ext in {".ts", ".tsx", ".js", ".jsx"}:
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
        ".css": "css",
        ".scss": "scss",
        ".json": "json",
        ".md": "md",
    }.get(ext, "")


async def generate_docs(cfg: AppCfg, force: bool = False) -> None:
    src_root = cfg.paths.forest_src
    if not src_root.exists():
        raise FileNotFoundError(f"src_root não encontrado: {src_root}")

    out_root = cfg.paths.output_root
    out_root.mkdir(parents=True, exist_ok=True)

    cfg.paths.state_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(cfg.paths.manifest_path)
    manifest.load()

    files = list(iter_source_files(
        src_root=src_root,
        include_exts=cfg.scan.include_extensions,
        exclude_dirs=cfg.scan.exclude_dirs,
        ignore_patterns=cfg.scan.ignore_patterns,
    ))

    imports_of, imported_by = build_import_graph(
        src_root=src_root,
        files=files,
        aliases=cfg.resolve.ts_path_aliases,
    )

    if cfg.docgen.template_mode == "file":
        if not cfg.docgen.template_file_path:
            raise ValueError("template_mode=file, mas template_file_path está vazio.")
        template = load_file_template(Path(cfg.docgen.template_file_path))
    else:
        template = load_builtin_template()

    api_key = (os.environ.get(cfg.llm.api_key_env) or cfg.llm.api_key_fallback or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY ausente. Defina env var ou llm.api_key_fallback.")

    groq = GroqClient(api_key=api_key)
    
    service_tier = (cfg.llm.service_tier or "").strip()
    # on_demand é default quando omitido. :contentReference[oaicite:6]{index=6}
    if service_tier.lower() in {"", "on_demand"}:
        service_tier_val = None
    else:
        service_tier_val = service_tier

    reasoning_effort = (cfg.llm.reasoning_effort or "").strip() or None

    params = GroqParams(
        temperature=cfg.llm.temperature,
        top_p=cfg.llm.top_p,
        max_completion_tokens=cfg.llm.max_completion_tokens,
        stream=cfg.llm.stream,
        service_tier=service_tier_val,
        reasoning_effort=reasoning_effort,
    )


    policy = RoutingPolicy(
        preferred_models=cfg.llm.routing.preferred_models,
        max_attempts_per_model=cfg.llm.retry.max_attempts_per_model,
        backoff_base_s=cfg.llm.retry.backoff_base_seconds,
        backoff_max_s=cfg.llm.retry.backoff_max_seconds,
    )

    router = ModelRouter(groq=groq, policy=policy, params=params)

    models = cfg.llm.routing.preferred_models
    if cfg.llm.routing.validate_with_models_endpoint:
        models = await router.validate_models()

    work: list[WorkItem] = []
    for f in files:
        out_path = doc_path_for(f.rel_path, out_root, cfg.docgen.output_layout)
        work.append(WorkItem(src=f, out_path=out_path, rel_key=f.rel_path.as_posix()))

    sem = asyncio.Semaphore(cfg.performance.max_concurrency)

    async def process_one(w: WorkItem) -> None:
        async with sem:
            raw = w.src.abs_path.read_text(encoding="utf-8", errors="ignore")
            raw = redact_secrets(raw)
            sha = sha256_text(raw)

            if (not force) and manifest.get_sha(w.rel_key) == sha and w.out_path.exists():
                return

            chunks = chunk_text_by_lines(
                raw,
                max_chars=cfg.docgen.max_chars_per_request,
                overlap_lines=cfg.docgen.chunk_overlap_lines,
            )

            partial_docs: list[str] = []
            used_models: list[str] = []

            for i, chunk in enumerate(chunks, start=1):
                rel_path = w.src.rel_path
                kind = _kind_from_ext(w.src.ext)
                fence = _code_fence_from_ext(w.src.ext)

                imports_links: list[tuple[Path, Path]] = []
                for e in imports_of.get(rel_path, []):
                    doc_rel = doc_path_for(e.target, out_root, cfg.docgen.output_layout).relative_to(out_root)
                    imports_links.append((e.target, doc_rel))

                imported_by_links: list[tuple[Path, Path]] = []
                for e in imported_by.get(rel_path, []):
                    doc_rel = doc_path_for(e.src, out_root, cfg.docgen.output_layout).relative_to(out_root)
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

                doc_txt, used_model = await router.generate(messages=messages, models=models)
                partial_docs.append(doc_txt.strip())
                used_models.append(used_model)

            final_doc = partial_docs[0]
            used_model_final = used_models[0] if used_models else "unknown"

            if len(partial_docs) > 1:
                merge_messages = [{
                    "role": "user",
                    "content": (
                        "Unifique as documentações parciais (chunks) abaixo em um único Markdown coerente. "
                        "Remova duplicações, mantenha a ordem, preserve todos os pontos relevantes. "
                        "Não invente nada.\n\n" + "\n\n---\n\n".join(partial_docs)
                    ),
                }]
                final_doc, used_model_final = await router.generate(messages=merge_messages, models=models)

            w.out_path.parent.mkdir(parents=True, exist_ok=True)
            w.out_path.write_text(final_doc.strip() + "\n", encoding="utf-8")

            manifest.set_entry(
                w.rel_key,
                ManifestEntry(
                    sha256=sha,
                    model=used_model_final,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                ),
            )

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
        await _write_index(cfg, work)

    await groq.close()


async def _write_index(cfg: AppCfg, work: list[WorkItem]) -> None:
    out_root = cfg.paths.output_root
    index_path = out_root / "INDEX.md"

    lines: list[str] = []
    lines.append("# Índice de documentação\n")
    lines.append("Gerado automaticamente pelo forest-portal-helper.\n")

    for w in sorted(work, key=lambda x: x.rel_key):
        doc_rel = w.out_path.relative_to(out_root).as_posix()
        lines.append(f"- {w.rel_key} -> [{doc_rel}]({doc_rel})")

    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
