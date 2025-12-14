from __future__ import annotations

from pathlib import Path


def doc_path_for(rel_src_path: Path, output_root: Path, layout: str) -> Path:
    parent = rel_src_path.parent
    stem = rel_src_path.stem

    if layout == "stem_folder":
        return output_root / "src" / parent / stem / f"{stem}.md"

    if layout == "flat":
        return output_root / "src" / parent / f"{stem}.md"

    raise ValueError(f"Unsupported output_layout: {layout}")
