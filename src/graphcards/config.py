"""Pydantic models and TOML loading for a GraphCards workspace."""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fsrs import Scheduler
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from graphcards.decks import Deck
from graphcards.errors import ConfigError
from graphcards.models import FrozenModel, resolve_config_path


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a number")
    return float(value)


class FsrsSettings(FrozenModel):
    """User-facing FSRS settings stored in TOML-friendly units."""

    desired_retention: Annotated[float, BeforeValidator(_number), Field(gt=0, le=1)] = 0.9
    maximum_interval: Annotated[int, Field(strict=True, gt=0)] = 36500
    learning_steps_minutes: tuple[Annotated[int, Field(strict=True, gt=0)], ...] = (1, 10)
    relearning_steps_minutes: tuple[Annotated[int, Field(strict=True, gt=0)], ...] = (10,)
    enable_fuzzing: StrictBool = True

    def create_scheduler(self) -> Scheduler:
        """Build an FSRS scheduler and translate library errors into config errors."""

        try:
            return Scheduler(
                desired_retention=self.desired_retention,
                maximum_interval=self.maximum_interval,
                learning_steps=tuple(
                    timedelta(minutes=minutes) for minutes in self.learning_steps_minutes
                ),
                relearning_steps=tuple(
                    timedelta(minutes=minutes) for minutes in self.relearning_steps_minutes
                ),
                enable_fuzzing=self.enable_fuzzing,
            )
        except (OverflowError, TypeError, ValueError) as error:
            raise ConfigError(f"invalid FSRS settings: {error}") from error


def _resolve_path(value: object, info: ValidationInfo) -> Path:
    return resolve_config_path(value, info)


class AppConfig(FrozenModel):
    model_config = FrozenModel.model_config | ConfigDict(arbitrary_types_allowed=True)
    state_path: Path = Path(".graphcards/state.sqlite3")
    display_timezone: ZoneInfo = Field(default_factory=lambda: ZoneInfo("UTC"))
    decks: tuple[Deck, ...] = ()
    fsrs: FsrsSettings = Field(default_factory=FsrsSettings)

    @field_validator("state_path", mode="before")
    @classmethod
    def resolve_single_path(cls, value: object, info: ValidationInfo) -> Path:
        return _resolve_path(value, info)

    @field_validator("decks", mode="before")
    @classmethod
    def resolve_decks(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("decks must be a list of deck files")
        context = info.context if isinstance(info.context, dict) else {}
        base = context.get("base")
        resolved: list[Deck] = []
        for deck_file in value:
            if not isinstance(deck_file, (str, Path)) or not str(deck_file).strip():
                raise ValueError("each deck entry must be a non-empty deck file path")
            path = Path(deck_file).expanduser()
            if not path.is_absolute() and isinstance(base, Path):
                path = base / path
            try:
                mode = path.stat().st_mode
            except OSError as error:
                raise ValueError(f"could not access deck file {path}: {error}") from error
            if S_ISDIR(mode):
                raise ValueError(f"each deck entry must be a deck file, not a directory: {path}")
            if not S_ISREG(mode):
                raise ValueError(f"each deck entry must be a regular deck file: {path}")
            resolved.append(Deck.load(path))
        return tuple(resolved)

    @model_validator(mode="after")
    def unique_deck_names(self) -> AppConfig:
        names = [deck.name for deck in self.decks]
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        if duplicates:
            raise ValueError(f"duplicate deck name: {duplicates[0]!r}")
        return self

    def deck(self, name: str) -> Deck:
        for deck in self.decks:
            if deck.name == name:
                return deck
        available = ", ".join(deck.name for deck in self.decks) or "none"
        raise ConfigError(f"unknown deck {name!r}; configured decks: {available}")


def load_config(path: str | Path = "graphcards.toml") -> AppConfig:
    """Load and validate one workspace configuration."""

    config_path = Path(path).expanduser().resolve()
    try:
        with config_path.open("rb") as config_file:
            data: dict[str, Any] = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise ConfigError(f"configuration file not found: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error
    except (OSError, UnicodeError) as error:
        raise ConfigError(f"could not read configuration {config_path}: {error}") from error

    try:
        config = AppConfig.model_validate(
            data,
            context={"base": config_path.parent},
        )
    except ValidationError as error:
        raise ConfigError(f"invalid configuration in {config_path}: {error}") from error
    config.fsrs.create_scheduler()
    return config
