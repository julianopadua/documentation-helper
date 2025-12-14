from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ManifestEntry:
    sha256: str
    model: str
    updated_at: str


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {"files": {}}

    def load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get_sha(self, rel_path: str) -> str | None:
        v = self._data.get("files", {}).get(rel_path)
        return None if not v else v.get("sha256")

    def set_entry(self, rel_path: str, entry: ManifestEntry) -> None:
        self._data.setdefault("files", {})[rel_path] = {
            "sha256": entry.sha256,
            "model": entry.model,
            "updated_at": entry.updated_at,
        }
