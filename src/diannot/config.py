"""Application configuration via pydantic-settings.

Sources, highest priority first: constructor args, ``DIANNOT_`` environment
variables (nested via ``__``), then ``diannot.toml`` in the working directory.
Themes and packs are data on disk; their default locations point at the
package's bundled assets.
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_THEMES_DIR = PACKAGE_DIR / "themes"
DEFAULT_PACKS_DIR = PACKAGE_DIR / "assets" / "packs"


class ModelsCfg(BaseModel):
    """Claude model IDs for each AI step."""

    structure: str = "claude-opus-4-8"
    summarize: str = "claude-opus-4-8"


class ProvidersCfg(BaseModel):
    """Which AI backend powers each feature.

    ``notes`` drives making notes (structuring imported material); ``study`` drives
    quiz/flashcard generation. ``"claude"`` uses the Claude Agent SDK (your login or
    key); ``"ollama"`` uses a local Ollama server — free, offline, no key.
    """

    notes: str = "claude"  # "claude" | "ollama" | "gemini"
    study: str = "claude"  # "claude" | "ollama" | "gemini"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"  # good quality + ~1.5 min/note on a laptop CPU
    ollama_vision_model: str = "llama3.2-vision"
    gemini_model: str = "gemini-2.5-flash"  # free-tier Flash; multimodal (also used for vision)


class RenderCfg(BaseModel):
    """Rendering defaults."""

    default_pack: str = "study_notes"
    default_theme: str = "circulatory"
    pdf_engine: str = "chromium"


class PathsCfg(BaseModel):
    """Filesystem locations."""

    output_dir: Path = Path("output")
    themes_dir: Path = DEFAULT_THEMES_DIR
    packs_dir: Path = DEFAULT_PACKS_DIR


def _config_path() -> Path:
    """Where ``diannot.toml`` lives: per-user AppData in the installed (frozen) app — whose
    program folder is read-only — else the working directory in dev."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
        return Path(base) / "diannot" / "diannot.toml"
    return Path("diannot.toml")


class Settings(BaseSettings):
    """Top-level Diannot settings."""

    model_config = SettingsConfigDict(
        env_prefix="DIANNOT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    models: ModelsCfg = ModelsCfg()
    providers: ProvidersCfg = ProvidersCfg()
    render: RenderCfg = RenderCfg()
    paths: PathsCfg = PathsCfg()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Resolve the toml path at instantiation (dynamic), so a Settings() read always matches
        # what update_config() writes — both go through _config_path().
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=_config_path()),
            file_secret_settings,
        )


def load_config_file(path: str | Path | None = None) -> dict:
    """Read ``diannot.toml`` into a dict (empty if it doesn't exist)."""
    p = Path(path or _config_path())
    if not p.exists():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _toml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def save_config_file(data: dict, path: str | Path | None = None) -> None:
    """Write a {section: {key: scalar}} dict back to ``diannot.toml``."""
    p = Path(path or _config_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section, table in data.items():
        lines.append(f"[{section}]")
        for key, value in table.items():
            lines.append(f"{key} = {_toml_scalar(value)}")
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")


def update_config(section: str, values: dict, path: str | Path | None = None) -> None:
    """Merge ``values`` into one ``[section]`` of ``diannot.toml``, preserving the rest."""
    path = path or _config_path()
    data = load_config_file(path)
    data.setdefault(section, {}).update(values)
    save_config_file(data, path)
