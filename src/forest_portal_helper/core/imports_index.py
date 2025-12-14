from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from forest_portal_helper.core.fs_scanner import SourceFile


_IMPORT_TS = re.compile(
    r"(^|\n)\s*(import\s+.*?\s+from\s+|export\s+\*\s+from\s+)[\"']([^\"']+)[\"']",
    re.MULTILINE,
)
_REQUIRE_TS = re.compile(r"require\(\s*[\"']([^\"']+)[\"']\s*\)")
_IMPORT_CSS = re.compile(r"@import\s+[\"']([^\"']+)[\"']")


@dataclass(frozen=True)
class ImportEdge:
    src: Path
    target: Path
    raw: str


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _resolve_candidate(
    base_dir: Path,
    raw: str,
    src_root: Path,
    aliases: dict[str, str],
) -> Path | None:
    raw = raw.strip()

    for prefix, mapped in aliases.items():
        if raw.startswith(prefix):
            # "@/x" -> <project_root>/<mapped>/x
            return (src_root.parent / mapped / raw[len(prefix):]).resolve()

    if raw.startswith("."):
        return (base_dir / raw).resolve()

    return None


def _expand_extensions(p: Path) -> list[Path]:
    exts = ["", ".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".scss", ".md"]
    out = [Path(str(p) + e) for e in exts]
    out += [
        p / "index.ts",
        p / "index.tsx",
        p / "index.js",
        p / "index.jsx",
    ]
    return out


def build_import_graph(
    src_root: Path,
    files: Iterable[SourceFile],
    aliases: dict[str, str],
) -> tuple[dict[Path, list[ImportEdge]], dict[Path, list[ImportEdge]]]:
    file_set = {f.abs_path.resolve() for f in files}
    rel_by_abs = {f.abs_path.resolve(): f.rel_path for f in files}

    imports_of: dict[Path, list[ImportEdge]] = {}
    imported_by: dict[Path, list[ImportEdge]] = {}

    for f in files:
        text = _read_text(f.abs_path)
        base_dir = f.abs_path.parent.resolve()

        raws: list[str] = []
        raws += [m.group(3) for m in _IMPORT_TS.finditer(text)]
        raws += [m.group(1) for m in _REQUIRE_TS.finditer(text)]
        raws += [m.group(1) for m in _IMPORT_CSS.finditer(text)]

        for raw in raws:
            resolved = _resolve_candidate(base_dir, raw, src_root, aliases)
            if resolved is None:
                continue

            target_abs: Path | None = None
            for cand in _expand_extensions(resolved):
                c = cand.resolve()
                if c in file_set:
                    target_abs = c
                    break

            if target_abs is None:
                continue

            src_rel = f.rel_path
            target_rel = rel_by_abs[target_abs]

            edge = ImportEdge(src=src_rel, target=target_rel, raw=raw)
            imports_of.setdefault(src_rel, []).append(edge)
            imported_by.setdefault(target_rel, []).append(edge)

    return imports_of, imported_by
