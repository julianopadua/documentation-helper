from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pathspec


@dataclass(frozen=True)
class SourceFile:
    abs_path: Path
    rel_path: Path
    ext: str

    @property
    def stem(self) -> str:
        return self.abs_path.stem


def _build_ignore_spec(patterns: list[str]) -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def iter_source_files(
    src_root: Path,
    include_exts: list[str],
    exclude_dirs: list[str],
    ignore_patterns: list[str],
) -> Iterable[SourceFile]:
    ignore = _build_ignore_spec(ignore_patterns)
    include = {e.lower() for e in include_exts}
    exclude = {d.lower() for d in exclude_dirs}

    for p in src_root.rglob("*"):
        rel = p.relative_to(src_root)

        if any(part.lower() in exclude for part in rel.parts):
            continue

        if ignore.match_file(rel.as_posix()):
            continue

        if p.is_file() and p.suffix.lower() in include:
            yield SourceFile(abs_path=p, rel_path=rel, ext=p.suffix.lower())
