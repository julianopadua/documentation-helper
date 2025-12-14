from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), "")
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
    state_dir_rel: str
    logs_dir_rel: str

    @property
    def forest_src(self) -> Path:
        return self.forest_portal_root / self.forest_portal_src_rel

    @property
    def output_root(self) -> Path:
        return self.helper_root / self.output_root_rel

    @property
    def state_dir(self) -> Path:
        return self.helper_root / self.state_dir_rel

    @property
    def logs_dir(self) -> Path:
        return self.helper_root / self.logs_dir_rel

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.json"


@dataclass(frozen=True)
class ThrottleCfg:
    enabled: bool
    min_interval_seconds: float
    min_remaining_tokens: int


@dataclass(frozen=True)
class ScanCfg:
    include_extensions: list[str]
    exclude_dirs: list[str]
    ignore_patterns: list[str]


@dataclass(frozen=True)
class ResolveCfg:
    ts_path_aliases: dict[str, str]


@dataclass(frozen=True)
class DocGenCfg:
    language: str
    tone: str
    output_layout: str
    write_project_index: bool
    max_chars_per_request: int
    chunk_overlap_lines: int
    snippet_max_lines_per_block: int
    max_snippet_blocks: int
    template_mode: str
    template_file_path: str


@dataclass(frozen=True)
class LlmRoutingCfg:
    validate_with_models_endpoint: bool
    preferred_models: list[str]


@dataclass(frozen=True)
class LlmRetryCfg:
    max_attempts_per_model: int
    backoff_base_seconds: float
    backoff_max_seconds: float


@dataclass(frozen=True)
class LlmCfg:
    provider: str
    api_key_env: str
    api_key_fallback: str
    temperature: float
    top_p: float
    max_completion_tokens: int
    stream: bool
    service_tier: str
    reasoning_effort: str
    routing: LlmRoutingCfg
    retry: LlmRetryCfg
    throttle: ThrottleCfg


@dataclass(frozen=True)
class PerformanceCfg:
    max_concurrency: int


@dataclass(frozen=True)
class AppCfg:
    paths: PathsCfg
    scan: ScanCfg
    resolve: ResolveCfg
    docgen: DocGenCfg
    llm: LlmCfg
    performance: PerformanceCfg


def load_config(config_path: Path) -> AppCfg:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw = _expand_env(raw)

    p = raw["paths"]
    paths = PathsCfg(
        forest_portal_root=Path(p["forest_portal_root"]),
        forest_portal_src_rel=p["forest_portal_src_rel"],
        helper_root=Path(p["helper_root"]),
        output_root_rel=p["output_root_rel"],
        state_dir_rel=p["state_dir_rel"],
        logs_dir_rel=p["logs_dir_rel"],
    )

    s = raw["scan"]
    scan = ScanCfg(
        include_extensions=list(s["include_extensions"]),
        exclude_dirs=list(s["exclude_dirs"]),
        ignore_patterns=list(s.get("ignore_patterns", [])),
    )

    r = raw.get("resolve", {})
    resolve = ResolveCfg(ts_path_aliases=dict(r.get("ts_path_aliases", {})))

    d = raw["docgen"]
    docgen = DocGenCfg(
        language=d["language"],
        tone=d["tone"],
        output_layout=d["output_layout"],
        write_project_index=bool(d["write_project_index"]),
        max_chars_per_request=int(d["max_chars_per_request"]),
        chunk_overlap_lines=int(d["chunk_overlap_lines"]),
        snippet_max_lines_per_block=int(d["snippet_max_lines_per_block"]),
        max_snippet_blocks=int(d["max_snippet_blocks"]),
        template_mode=d.get("template_mode", "builtin"),
        template_file_path=d.get("template_file_path", ""),
    )

    l = raw["llm"]
    routing = LlmRoutingCfg(
        validate_with_models_endpoint=bool(l["routing"]["validate_with_models_endpoint"]),
        preferred_models=list(l["routing"]["preferred_models"]),
    )
    retry = LlmRetryCfg(
        max_attempts_per_model=int(l["retry"]["max_attempts_per_model"]),
        backoff_base_seconds=float(l["retry"]["backoff_base_seconds"]),
        backoff_max_seconds=float(l["retry"]["backoff_max_seconds"]),
    )
    t = l.get("throttle", {})
    throttle = ThrottleCfg(
        enabled=bool(t.get("enabled", True)),
        min_interval_seconds=float(t.get("min_interval_seconds", 2.2)),
        min_remaining_tokens=int(t.get("min_remaining_tokens", 800)),
    )

    llm = LlmCfg(
        provider=l["provider"],
        api_key_env=l["api_key_env"],
        api_key_fallback=l.get("api_key_fallback", ""),
        temperature=float(l["temperature"]),
        top_p=float(l["top_p"]),
        max_completion_tokens=int(l["max_completion_tokens"]),
        stream=bool(l["stream"]),
        service_tier=l.get("service_tier", "on_demand"),
        reasoning_effort=l.get("reasoning_effort", "medium"),
        routing=routing,
        retry=retry,
        throttle=throttle,
    )

    perf = raw.get("performance", {})
    performance = PerformanceCfg(max_concurrency=int(perf.get("max_concurrency", 4)))

    return AppCfg(
        paths=paths,
        scan=scan,
        resolve=resolve,
        docgen=docgen,
        llm=llm,
        performance=performance,
    )
