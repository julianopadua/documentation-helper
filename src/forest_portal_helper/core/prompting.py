from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import importlib.resources as ir


@dataclass(frozen=True)
class PromptContext:
    rel_path: Path
    file_kind: str
    code_fence: str
    code: str
    imports_links: list[tuple[Path, Path]]
    imported_by_links: list[tuple[Path, Path]]


def load_builtin_template() -> str:
    pkg = ir.files("forest_portal_helper") / "templates" / "doc_prompt.md"
    return pkg.read_text(encoding="utf-8")


def load_file_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _md_links(links: Iterable[tuple[Path, Path]]) -> str:
    lines = []
    for src_rel, doc_rel in links:
        lines.append(f"- {src_rel.as_posix()} -> [{doc_rel.as_posix()}]({doc_rel.as_posix()})")
    return "\n".join(lines) if lines else "- (nenhum)"


def render_messages(
    template: str,
    ctx: PromptContext,
    language: str,
    tone: str,
    snippet_max_lines_per_block: int,
    max_snippet_blocks: int,
) -> list[dict[str, str]]:
    user = template.format(
        language=language,
        tone=tone,
        rel_path=ctx.rel_path.as_posix(),
        file_kind=ctx.file_kind,
        imports_md=_md_links(ctx.imports_links),
        imported_by_md=_md_links(ctx.imported_by_links),
        max_snippet_blocks=max_snippet_blocks,
        snippet_max_lines_per_block=snippet_max_lines_per_block,
        code_fence=ctx.code_fence,
        code=ctx.code,
    )
    return [{"role": "user", "content": user}]
