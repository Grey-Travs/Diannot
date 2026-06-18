"""Application configuration via pydantic-settings.

Sources, highest priority first: constructor args, ``DIANNOT_`` environment
variables (nested via ``__``), then ``diannot.toml`` in the working directory.
Themes and packs are data on disk; their default locations point at the
package's bundled assets.
"""
from __future__ import annotations

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


class Settings(BaseSettings):
    """Top-level Diannot settings."""

    model_config = SettingsConfigDict(
        env_prefix="DIANNOT_",
        env_nested_delimiter="__",
        toml_file="diannot.toml",
        extra="ignore",
    )

    models: ModelsCfg = ModelsCfg()
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
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
