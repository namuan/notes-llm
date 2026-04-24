from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from llm_client import LLMProfile

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


@dataclass(slots=True)
class Config:
    base_dir: Path
    notes_account: str
    wiki_folder: str
    subfolders: list[str]
    llm_default_profile: str
    llm_lint_profile: str
    llm_profiles: dict[str, LLMProfile]
    poll_interval_seconds: int
    use_fswatch: bool
    batch_mode: bool
    lint_enabled: bool
    lint_hour: int
    supported_extensions: tuple[str, ...]
    max_file_size_mb: int
    max_note_length_chars: int
    cross_reference_style: str
    state_path: Path
    schema_path: Path
    lock_path: Path
    inbox_dir: Path
    processed_dir: Path
    cache_dir: Path
    log_path: Path


def load_llm_profiles(config: dict[str, Any]) -> dict[str, LLMProfile]:
    profiles: dict[str, LLMProfile] = {}
    for name, profile_config in config.get("llm", {}).get("profiles", {}).items():
        profiles[name] = LLMProfile(
            name=name,
            base_url=profile_config["base_url"],
            model=profile_config["model"],
            max_tokens=profile_config.get("max_tokens", 8192),
            api_key_env=profile_config.get("api_key_env", ""),
            api_key_value=profile_config.get("api_key_value", ""),
            extra_headers=profile_config.get("extra_headers", {}) or {},
            temperature=profile_config.get("temperature", 0.3),
            timeout_seconds=profile_config.get("timeout_seconds", 120),
            api_version=profile_config.get("api_version", ""),
        )
    return profiles


def _load_dotenv_if_present(base_dir: Path) -> None:
    if load_dotenv is None:
        return
    dotenv_path = base_dir / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_config(config_path: str | Path) -> Config:
    config_file = Path(config_path).expanduser().resolve()
    base_dir = config_file.parent
    _load_dotenv_if_present(base_dir)

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    profiles = load_llm_profiles(raw)

    llm_config = raw.get("llm", {})
    default_profile = llm_config.get("default_profile", "")
    lint_profile = llm_config.get("lint_profile", default_profile)
    if default_profile and default_profile not in profiles:
        raise ValueError(f"Unknown llm.default_profile: {default_profile}")
    if lint_profile and lint_profile not in profiles:
        raise ValueError(f"Unknown llm.lint_profile: {lint_profile}")

    supported_extensions = tuple(
        ext.lower()
        for ext in raw.get(
            "supported_extensions", [".md", ".txt", ".pdf", ".html", ".csv", ".json"]
        )
    )

    lock_path = raw.get("lock_path", ".lock")

    return Config(
        base_dir=base_dir,
        notes_account=raw.get("notes_account", "iCloud"),
        wiki_folder=raw.get("wiki_folder", "Wiki"),
        subfolders=list(
            raw.get("subfolders", ["Sources", "Entities", "Concepts", "Synthesis"])
        ),
        llm_default_profile=default_profile,
        llm_lint_profile=lint_profile,
        llm_profiles=profiles,
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 30)),
        use_fswatch=bool(raw.get("use_fswatch", True)),
        batch_mode=bool(raw.get("batch_mode", False)),
        lint_enabled=bool(raw.get("lint_enabled", True)),
        lint_hour=int(raw.get("lint_hour", 3)),
        supported_extensions=supported_extensions,
        max_file_size_mb=int(raw.get("max_file_size_mb", 10)),
        max_note_length_chars=int(raw.get("max_note_length_chars", 30000)),
        cross_reference_style=raw.get("cross_reference_style", "inline"),
        state_path=_resolve_path(base_dir, raw.get("state_path", "state.json")),
        schema_path=_resolve_path(base_dir, raw.get("schema_path", "schema.md")),
        lock_path=_resolve_path(base_dir, lock_path),
        inbox_dir=(base_dir / "inbox").resolve(),
        processed_dir=(base_dir / "processed").resolve(),
        cache_dir=(base_dir / "cache").resolve(),
        log_path=_resolve_path(base_dir, raw.get("log_path", "daemon.log")),
    )
