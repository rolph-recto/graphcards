"""Shared JSON/TOML/YAML deck aggregates and exercise-generator infrastructure."""

from __future__ import annotations

import json
import random
import tomllib
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from stat import S_ISREG
from types import MappingProxyType
from typing import Annotated, ClassVar, cast

from jinja2 import StrictUndefined, Template, TemplateError, meta
from jinja2.sandbox import SandboxedEnvironment
from pydantic import (
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from yaml import SafeLoader, YAMLError
from yaml import load as yaml_load
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent, NodeEvent
from yaml.nodes import MappingNode

from graphcards.errors import ConfigError, PresentationError
from graphcards.models import Card, CardKey, CardView, Exercise, FrozenModel

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

MAX_TEMPLATE_LENGTH = 100_000
MAX_RENDERED_LENGTH = 1_000_000
TemplateSource = Annotated[StrictStr, StringConstraints(strip_whitespace=False)]


class _SafeTemplateEnvironment(SandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**"})

    def call_binop(self, context: object, operator: str, left: object, right: object) -> object:
        if operator == "*":
            if (
                isinstance(left, int)
                and isinstance(right, (str, bytes, list, tuple))
                and abs(left) * len(right) > MAX_RENDERED_LENGTH
            ):
                raise ValueError(f"template multiplication exceeds {MAX_RENDERED_LENGTH}")
            if (
                isinstance(right, int)
                and isinstance(left, (str, bytes, list, tuple))
                and abs(right) * len(left) > MAX_RENDERED_LENGTH
            ):
                raise ValueError(f"template multiplication exceeds {MAX_RENDERED_LENGTH}")
        elif operator == "**" and isinstance(right, int) and abs(right) > 10_000:
            raise ValueError("template exponent is too large")
        return super().call_binop(context, operator, left, right)


_TEMPLATE_ENVIRONMENT = _SafeTemplateEnvironment(
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
    undefined=StrictUndefined,
)


@lru_cache(maxsize=256)
def _template(source: str) -> Template:
    return _TEMPLATE_ENVIRONMENT.from_string(source)


def _render_template(source: str, context: Mapping[str, object]) -> str:
    try:
        chunks: list[str] = []
        length = 0
        for chunk in _template(source).generate(**context):
            length += len(chunk)
            if length > MAX_RENDERED_LENGTH:
                raise ValueError(f"rendered output exceeds {MAX_RENDERED_LENGTH} characters")
            chunks.append(chunk)
        return "".join(chunks)
    except Exception as error:
        raise PresentationError(f"could not render card template: {error}") from error


def _nonblank(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-blank string")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    ):
        raise ValueError("must not contain control characters")
    return value


def _template_nonblank(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-blank string")
    return value


def _json_value(value: object, path: str = "data", depth: int = 0) -> None:
    if depth > 100:
        raise ValueError(f"{path} is nested too deeply")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{path} must contain JSON-compatible finite numbers")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _json_value(item, f"{path}.{key}", depth + 1)
        return
    raise ValueError(f"{path} must contain only JSON-compatible values")


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


class _DeckYamlLoader(SafeLoader):
    """Safe YAML loader with a deliberately small deck data language.

    Anchors and aliases are rejected instead of expanded. This keeps the decoded document a
    simple JSON-compatible tree and makes cyclic or resource-amplifying alias graphs impossible.
    Merge keys are rejected for the same reason; a quoted ``"<<"`` remains an ordinary key.
    """

    def compose_node(self, parent: object, index: object) -> object:
        event = self.peek_event()
        if isinstance(event, AliasEvent):
            event = self.get_event()
            raise ComposerError(
                None,
                None,
                "YAML aliases are not supported in deck files",
                event.start_mark,
            )
        if isinstance(event, NodeEvent) and event.anchor is not None:
            event = self.get_event()
            raise ComposerError(
                None,
                None,
                "YAML anchors are not supported in deck files",
                event.start_mark,
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: object, deep: bool = False) -> dict[str, object]:
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                None,
                None,
                "expected a YAML mapping",
                getattr(node, "start_mark", None),
            )
        mapping: dict[str, object] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "YAML merge keys are not supported in deck files",
                    key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "deck mapping keys must be strings",
                    key_node.start_mark,
                )
            if key in mapping:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate mapping key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _yaml_json_value(
    value: object,
    path: str = "data",
    depth: int = 0,
    active: set[int] | None = None,
) -> None:
    """Validate decoded YAML as an acyclic, finite JSON-compatible value tree."""

    if depth > 100:
        raise ValueError(f"{path} is nested too deeply")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{path} must contain JSON-compatible finite numbers")
        return
    if active is None:
        active = set()
    value_id = id(value)
    if value_id in active:
        raise ValueError(f"{path} must not contain cyclic YAML aliases")
    active.add(value_id)
    try:
        if isinstance(value, list):
            for index, item in enumerate(value):
                _yaml_json_value(item, f"{path}[{index}]", depth + 1, active)
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} object keys must be strings")
                _yaml_json_value(item, f"{path}.{key}", depth + 1, active)
            return
    finally:
        active.remove(value_id)
    raise ValueError(f"{path} must contain only JSON-compatible values")


def _yaml_error_message(error: YAMLError) -> str:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None)
    if mark is not None and problem:
        return f"{problem} at line {mark.line + 1}, column {mark.column + 1}"
    return str(error)


class Entity(FrozenModel):
    """One entity with a stable ID and arbitrary JSON-compatible metadata."""

    model_config = FrozenModel.model_config | ConfigDict(extra="allow")
    id: StrictStr

    @field_validator("id")
    @classmethod
    def require_id(cls, value: str) -> str:
        return cast(str, _nonblank(value))

    @model_validator(mode="after")
    def validate_extra_data(self) -> Entity:
        _json_value(self.__pydantic_extra__ or {})
        return self

    @property
    def model_extra(self) -> Mapping[str, object] | None:
        extra = self.__pydantic_extra__
        return cast(Mapping[str, object], _freeze_json(extra or {}))

    @property
    def data(self) -> Mapping[str, JsonValue]:
        values = self.model_dump(exclude={"id"}, mode="python")
        return cast(Mapping[str, JsonValue], _freeze_json(values))


@dataclass(frozen=True, slots=True)
class ExerciseGeneratorContext:
    """Immutable per-operation context supplied to an exercise generator."""

    deck_id: str
    entities: Mapping[str, Entity]
    rng: random.Random


class ExerciseGenerator(FrozenModel, ABC):
    """Validated deck configuration and behavior for one exercise generator."""

    id: StrictStr
    type: StrictStr
    front_template: TemplateSource | None = None
    back_template: TemplateSource | None = None
    template_context_names: ClassVar[frozenset[str]] = frozenset()
    type_name: ClassVar[str]
    _registry: ClassVar[dict[str, type[ExerciseGenerator]]] = {}

    @field_validator("id", "type")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        return cast(str, _nonblank(value))

    @field_validator("front_template", "back_template")
    @classmethod
    def validate_template_source(cls, value: str | None) -> str | None:
        if value is not None:
            _template_nonblank(value)
            if len(value) > MAX_TEMPLATE_LENGTH:
                raise ValueError(f"must not exceed {MAX_TEMPLATE_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def validate_templates(self) -> ExerciseGenerator:
        for field_name in ("front_template", "back_template"):
            source = getattr(self, field_name)
            if source is None:
                continue
            try:
                _template(source)
                unknown = (
                    meta.find_undeclared_variables(_TEMPLATE_ENVIRONMENT.parse(source))
                    - self.template_context_names
                )
                if unknown:
                    names = ", ".join(sorted(unknown))
                    raise ValueError(f"uses unknown template variable(s): {names}")
            except TemplateError as error:
                raise ValueError(f"{field_name} is not valid Jinja: {error}") from error
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        """Validate references after the complete entity set is available."""

    @property
    @abstractmethod
    def target_ids(self) -> tuple[str, ...]:
        """The scheduled target IDs in declared generator order."""

    @classmethod
    def register(cls, generator_type: type[ExerciseGenerator]) -> type[ExerciseGenerator]:
        cls._registry[generator_type.type_name] = generator_type
        return generator_type

    def _key(self, entity_id: str, deck_id: str) -> CardKey:
        if entity_id not in self.target_ids:
            raise PresentationError(
                f"generator {self.id!r} does not generate an exercise for entity {entity_id!r}"
            )
        return CardKey.exercise(deck_id, self.id, entity_id)

    @abstractmethod
    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        """Generate one semantic exercise for a target entity."""

    @abstractmethod
    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        """Render one semantic exercise using the supplied entity registry."""

    def validation_exercises(self, context: ExerciseGeneratorContext) -> tuple[Exercise, ...]:
        """Return deterministic exercises covering this generator for render preflight."""

        context = ExerciseGeneratorContext(context.deck_id, context.entities, random.Random(0))
        return tuple(self.generate(target_id, context) for target_id in self.target_ids)


class DeckDocument(FrozenModel):
    """The complete study-content document loaded from a JSON, TOML, or YAML deck file."""

    name: StrictStr | None = None
    entities: tuple[Entity, ...]
    exercises: tuple[ExerciseGenerator, ...]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None:
            _nonblank(value)
        return value

    @model_validator(mode="before")
    @classmethod
    def dispatch_generators(cls, value: object) -> object:
        """Dispatch generator envelopes before validating the complete document."""

        if not isinstance(value, Mapping):
            return value
        raw_exercises = value.get("exercises")
        if not isinstance(raw_exercises, (list, tuple)):
            return value
        dispatched: list[object] = []
        for item in raw_exercises:
            if not isinstance(item, Mapping):
                dispatched.append(item)
                continue
            kind = item.get("type")
            runtime_class = ExerciseGenerator._registry.get(kind) if isinstance(kind, str) else None
            if runtime_class is None:
                raise ValueError(f"unknown exercise generator type {kind!r}")
            dispatched.append(runtime_class.model_validate(item))
        result = dict(value)
        result["exercises"] = dispatched
        return result

    @model_validator(mode="after")
    def validate_registry(self) -> DeckDocument:
        entity_ids = tuple(entity.id for entity in self.entities)
        if len(set(entity_ids)) != len(entity_ids):
            duplicate = next(item for item in entity_ids if entity_ids.count(item) > 1)
            raise ValueError(f"duplicate entity ID: {duplicate!r}")
        generator_ids = tuple(generator.id for generator in self.exercises)
        if len(set(generator_ids)) != len(generator_ids):
            duplicate = next(item for item in generator_ids if generator_ids.count(item) > 1)
            raise ValueError(f"duplicate generator ID: {duplicate!r}")
        known = set(entity_ids)
        for generator in self.exercises:
            generator.validate_references(known)
        return self


def _require_refs(generator_id: str, refs: Sequence[str], known: set[str], label: str) -> None:
    for ref in refs:
        if ref not in known:
            raise ValueError(f"generator {generator_id!r} references unknown {label} {ref!r}")


@dataclass(frozen=True)
class Deck:
    """Immutable runtime aggregate containing all content and generators for one deck."""

    name: str
    path: Path
    document: DeckDocument
    entities: Mapping[str, Entity]
    generators: tuple[ExerciseGenerator, ...]

    @property
    def display_name(self) -> str:
        return self.document.name or self.name

    def _generators_by_entity(self) -> dict[str, ExerciseGenerator]:
        """Choose one stable exercise generator for every targeted entity.

        A deck schedules entities, not generator/entity pairs.  Sorting by generator ID makes
        the selected exercise type independent of deck declaration order when configurations
        overlap intentionally.
        """

        selected: dict[str, ExerciseGenerator] = {}
        for generator in sorted(self.generators, key=lambda item: item.id):
            for entity_id in generator.target_ids:
                selected.setdefault(entity_id, generator)
        return selected

    @property
    def target_entity_ids(self) -> tuple[str, ...]:
        """The unique entities represented by the deck's scheduled exercises."""

        return tuple(self._generators_by_entity())

    @classmethod
    def from_document(cls, document: DeckDocument, *, name: str, path: Path) -> Deck:
        entities = MappingProxyType({entity.id: entity for entity in document.entities})
        generators = document.exercises
        return cls(name, path, document, entities, generators)

    @classmethod
    def load(cls, value: str | Path) -> Deck:
        """Load a JSON, TOML, or YAML deck and translate file/configuration failures."""
        try:
            path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise ConfigError(f"could not resolve deck path {value}: {error}") from error
        try:
            mode = path.stat().st_mode
        except OSError as error:
            raise ConfigError(f"could not access deck file {path}: {error}") from error
        if not S_ISREG(mode):
            raise ConfigError(f"deck path is not a file: {path}")
        extension = path.suffix.lower()
        if extension not in {".json", ".toml", ".yaml", ".yml"}:
            raise ConfigError(
                f"unsupported deck file extension for {path}: {path.suffix or '(none)'}; "
                "expected .json, .toml, .yaml, or .yml"
            )
        try:
            if extension == ".json":
                raw = json.loads(
                    path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
                )
            elif extension == ".toml":
                with path.open("rb") as deck_file:
                    raw = tomllib.load(deck_file)
            else:
                raw = yaml_load(path.read_text(encoding="utf-8"), Loader=_DeckYamlLoader)
                _yaml_json_value(raw)
            if not isinstance(raw, Mapping):
                raise TypeError("deck document must be an object")
            document = DeckDocument.model_validate(raw)
            # A deck's path is its stable identity source. The display name is not.
            name = path.parent.name
            _nonblank(name)
            deck = cls.from_document(document, name=name, path=path)
            try:
                deck._validate_rendering()
            except PresentationError as error:
                raise ConfigError(f"invalid deck {path}: {error}") from error
            return deck
        except ConfigError:
            raise
        except YAMLError as error:
            raise ConfigError(f"invalid YAML deck {path}: {_yaml_error_message(error)}") from error
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"invalid TOML deck {path}: {error}") from error
        except (OSError, UnicodeError) as error:
            raise ConfigError(f"could not read deck file {path}: {error}") from error
        except (
            json.JSONDecodeError,
            RecursionError,
            ValidationError,
            TypeError,
            ValueError,
        ) as error:
            message = _validation_message(error)
            raise ConfigError(f"invalid deck {path}: {message}") from error

    def _validate_rendering(self) -> None:
        """Preflight generated views so template errors fail before synchronization."""

        context = ExerciseGeneratorContext(self.name, self.entities, random.Random(0))
        for generator in self.generators:
            for exercise in generator.validation_exercises(context):
                self.render(exercise, rng=random.Random(0))

    def generate_all(self, *, rng: random.Random | None = None) -> dict[str, Card]:
        random_source = rng or random.Random()
        context = ExerciseGeneratorContext(self.name, self.entities, random_source)
        generated: dict[str, Card] = {}
        for target_id, generator in self._generators_by_entity().items():
            exercise = generator.generate(target_id, context)
            card_id = exercise.card_key.digest
            existing = generated.get(card_id)
            if existing is not None and existing.card_key != exercise.card_key:
                raise PresentationError("SHA-256 collision between generated exercises")
            generated[card_id] = exercise
        return generated

    def generate(self, card_key: CardKey, *, rng: random.Random | None = None) -> Exercise:
        if card_key.deck_id != self.name or card_key.generator_id is None:
            raise PresentationError(f"card {card_key.digest} does not belong to deck {self.name!r}")
        context = ExerciseGeneratorContext(self.name, self.entities, rng or random.Random())
        selected = self._generators_by_entity().get(card_key.entity_id)
        if selected is None or selected.id != card_key.generator_id:
            raise PresentationError(
                f"deck {self.name!r} no longer generates card {card_key.digest}"
            )
        for generator in self.generators:
            if generator.id == card_key.generator_id:
                return generator.generate(cast(str, card_key.entity_id), context)
        raise PresentationError(
            f"deck {self.name!r} no longer has generator {card_key.generator_id!r}"
        )

    def render(self, exercise: Exercise, *, rng: random.Random | None = None) -> CardView:
        try:
            belongs_to_deck = exercise.card_key.deck_id == self.name
        except (AttributeError, TypeError) as error:
            raise PresentationError("exercise has an invalid card identity") from error
        if not belongs_to_deck:
            raise PresentationError(f"exercise does not belong to deck {self.name!r}")
        try:
            exercise_generator_id = exercise.generator_id
        except AttributeError as error:
            raise PresentationError("exercise has an invalid generator identity") from error
        context = ExerciseGeneratorContext(self.name, self.entities, rng or random.Random())
        for generator in self.generators:
            if generator.id == exercise_generator_id:
                return generator.render(exercise, context)
        raise PresentationError(
            f"deck {self.name!r} no longer has generator {exercise_generator_id!r}"
        )


def _validation_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return str(error.errors(include_url=False)[0]["msg"]).removeprefix("Value error, ")
    return str(error)


__all__ = [
    "Deck",
    "DeckDocument",
    "Entity",
    "ExerciseGenerator",
    "ExerciseGeneratorContext",
]
