from future import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"${([A-Za-z][A-Za-z0-9_]*)}")

def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            var = m.group(1)
            return os.environ.get(var, "")
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value

@dataclass(frozen=True)
class PathsCfg:
    forest_portal_root: Path
    forest_portal_src_rel: str
    helper_root: Path
    output_root_rel: str
    template_dir_rel: str
    state_dir_rel: str
    logs_dir_rel: str