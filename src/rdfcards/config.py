"""Pydantic models and TOML loading for an RDFCards workspace."""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

from fsrs import Scheduler
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from rdfcards.decks import DeckKind
from rdfcards.errors import ConfigError
from rdfcards.models import TargetKind


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a number")
    return float(value)


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


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
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("must be a non-empty file path")
    path = Path(value).expanduser()
    context = info.context if isinstance(info.context, dict) else {}
    base = context.get("base")
    # Validation context makes every configured path relative to the TOML file,
    # independent of the caller's current working directory.
    if not path.is_absolute() and isinstance(base, Path):
        path = base / path
    return path.resolve()


class DeckDefinition(FrozenModel):
    model_config = FrozenModel.model_config | ConfigDict(
        validate_by_alias=True, validate_by_name=True
    )

    name: Annotated[str, Field(min_length=1)]
    target: TargetKind
    kind: type[DeckKind]
    query_path: Path = Field(validation_alias="query")

    @field_validator("kind", mode="before")
    @classmethod
    def resolve_kind(cls, value: object) -> object:
        kind = DeckKind.from_name(value.strip()) if isinstance(value, str) else value
        return DeckKind.validate_kind_class(kind)

    @field_validator("query_path", mode="before")
    @classmethod
    def resolve_query_path(cls, value: object, info: ValidationInfo) -> Path:
        return _resolve_path(value, info)


class AppConfig(FrozenModel):
    state_path: Path = Path(".rdfcards/state.sqlite3")
    sources: tuple[Path, ...] = ()
    decks: tuple[DeckDefinition, ...] = ()
    fsrs: FsrsSettings = Field(default_factory=FsrsSettings)

    @field_validator("state_path", mode="before")
    @classmethod
    def resolve_single_path(cls, value: object, info: ValidationInfo) -> Path:
        return _resolve_path(value, info)

    @field_validator("sources", mode="before")
    @classmethod
    def resolve_sources(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        return tuple(_resolve_path(source, info) for source in value)

    @model_validator(mode="after")
    def unique_deck_names(self) -> AppConfig:
        names = [deck.name for deck in self.decks]
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        if duplicates:
            raise ValueError(f"duplicate deck name: {duplicates[0]!r}")
        return self

    def deck(self, name: str) -> DeckDefinition:
        for deck in self.decks:
            if deck.name == name:
                return deck
        available = ", ".join(deck.name for deck in self.decks) or "none"
        raise ConfigError(f"unknown deck {name!r}; configured decks: {available}")


def load_config(path: str | Path = "rdfcards.toml") -> AppConfig:
    """Load and validate one workspace configuration."""

    config_path = Path(path).expanduser().resolve()
    try:
        with config_path.open("rb") as config_file:
            data: dict[str, Any] = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise ConfigError(f"configuration file not found: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error

    try:
        config = AppConfig.model_validate(
            data,
            context={"base": config_path.parent},
        )
    except ValidationError as error:
        raise ConfigError(f"invalid configuration in {config_path}: {error}") from error
    config.fsrs.create_scheduler()
    return config
