"""Shared JSON/TOML/YAML deck aggregates and exercise-generator infrastructure."""

from __future__ import annotations

import json
import random
import tomllib
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from stat import S_ISREG
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Literal, cast, get_args, get_origin, get_type_hints

from jinja2 import StrictUndefined, Template, TemplateError, meta
from jinja2.sandbox import SandboxedEnvironment
from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
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
from graphcards.references import EntityId, EntityIdListMarker, validate_entity_id
from graphcards.scheduling import DailyLimits, DeckSchedulingSettings

MAX_TEMPLATE_LENGTH = 100_000
MAX_RENDERED_LENGTH = 1_000_000
TemplateSource = Annotated[StrictStr, StringConstraints(strip_whitespace=False)]
_UNSAFE_TEMPLATE_ATTRIBUTES = frozenset(
    {
        "construct",
        "copy",
        "dict",
        "from_orm",
        "json",
        "model_copy",
        "model_computed_fields",
        "model_config",
        "model_construct",
        "model_dump",
        "model_dump_json",
        "model_extra",
        "model_fields",
        "model_fields_set",
        "model_json_schema",
        "model_parametrized_name",
        "model_post_init",
        "model_rebuild",
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
        "parse_file",
        "parse_obj",
        "parse_raw",
        "schema",
        "schema_json",
        "update_forward_refs",
        "validate",
    }
)
_RESERVED_ENTITY_FIELDS = frozenset(
    {
        "construct",
        "copy",
        "dict",
        "from_orm",
        "json",
        "model_computed_fields",
        "model_config",
        "model_construct",
        "model_copy",
        "model_dump",
        "model_dump_json",
        "model_extra",
        "model_fields",
        "model_fields_set",
        "model_json_schema",
        "model_parametrized_name",
        "model_post_init",
        "model_rebuild",
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
        "parse_file",
        "parse_obj",
        "parse_raw",
        "schema",
        "schema_json",
        "update_forward_refs",
        "validate",
    }
)


class _SafeTemplateEnvironment(SandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**"})

    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:
        if attr in _UNSAFE_TEMPLATE_ATTRIBUTES:
            return False
        return super().is_safe_attribute(obj, attr, value)

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
    autoescape=True,
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
    return validate_entity_id(value)


def _template_nonblank(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-blank string")
    return value


def _json_value(value: object, path: str = "entity", depth: int = 0) -> None:
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
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _copy_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _copy_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_json(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_json(item) for item in value)
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


def _model_validate_unique_json(
    cls: type[FrozenModel],
    json_data: str | bytes | bytearray,
    *,
    strict: bool | None,
    extra: Literal["allow", "ignore", "forbid"] | None,
    context: Any | None,
    by_alias: bool | None,
    by_name: bool | None,
) -> Any:
    try:
        value = json.loads(json_data, object_pairs_hook=_unique_json_object)
    except (RecursionError, TypeError, ValueError) as error:
        raise ValidationError.from_exception_data(
            cls.__name__,
            [
                {
                    "type": "value_error",
                    "loc": (),
                    "input": json_data,
                    "ctx": {"error": str(error)},
                }
            ],
        ) from error
    return cls.model_validate(
        value,
        strict=strict,
        extra=extra,
        context=context,
        by_alias=by_alias,
        by_name=by_name,
    )


class Entity(FrozenModel):
    """One entity with a stable ID and arbitrary immutable JSON-compatible fields."""

    model_config = FrozenModel.model_config | ConfigDict(extra="allow")
    id: EntityId

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return cast(str, _nonblank(value))

    @model_validator(mode="before")
    @classmethod
    def _reject_reserved_fields(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        forbidden = sorted(
            key
            for key in value
            if isinstance(key, str) and (key.startswith("_") or key in _RESERVED_ENTITY_FIELDS)
        )
        if forbidden:
            raise ValueError(f"reserved entity field: {forbidden[0]!r}")
        return value

    @model_validator(mode="after")
    def _validate_extra_data(self) -> Entity:
        extra = self.__pydantic_extra__ or {}
        _json_value(extra)
        object.__setattr__(self, "__pydantic_extra__", _copy_json(extra))
        return self

    @property
    def model_extra(self) -> None:
        raise AttributeError("Entity model extras are private")

    def model_copy(
        self, *, update: Mapping[str, object] | None = None, deep: bool = False
    ) -> Entity:
        if update is None:
            return cast(Entity, super().model_copy(deep=deep))
        values = self.model_dump(mode="python")
        values.update(update)
        return type(self).model_validate(values)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Entity:
        return cls.model_validate(values)

    @classmethod
    def construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Entity:
        return cls.model_validate(values)

    def copy(
        self,
        *,
        include: Any = None,
        exclude: Any = None,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Entity:
        values = self.model_dump(mode="python", include=include, exclude=exclude)
        if update is not None:
            values.update(update)
        return type(self).model_validate(values)

    @classmethod
    def parse_raw(cls, b: str | bytes | bytearray, *args: Any, **kwargs: Any) -> Entity:
        return cls.model_validate_json(b)

    @classmethod
    def parse_file(cls, path: str | Path, *args: Any, **kwargs: Any) -> Entity:
        return cls.model_validate_json(Path(path).read_bytes())

    @classmethod
    def model_validate_json(
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        extra: Literal["allow", "ignore", "forbid"] | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Entity:
        return cast(
            Entity,
            _model_validate_unique_json(
                cls,
                json_data,
                strict=strict,
                extra=extra,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            ),
        )

    def __getattr__(self, name: str) -> object:
        """Expose validated extra fields as immutable direct attributes."""

        try:
            extra = object.__getattribute__(self, "__pydantic_extra__")
        except AttributeError:
            extra = None
        if extra is not None and name in extra:
            return _freeze_json(extra[name])
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


class EntityGroup(FrozenModel):
    """An ordered, reusable list of concrete entity IDs."""

    id: StrictStr
    entities: tuple[EntityId, ...]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return cast(str, _nonblank(value))

    @model_validator(mode="after")
    def validate_members(self) -> EntityGroup:
        if not self.entities:
            raise ValueError(f"group {self.id!r} must define at least one entity")
        if len(self.entities) != len(set(self.entities)):
            raise ValueError(f"group {self.id!r} has duplicate entities")
        return self


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

    def scheduled_keys(self, entities: Mapping[str, Entity]) -> tuple[tuple[str, str | None], ...]:
        """Return the scheduled entity and optional cloze ID pairs."""

        return tuple((entity_id, None) for entity_id in self.target_ids)

    @classmethod
    def register(cls, generator_type: type[ExerciseGenerator]) -> type[ExerciseGenerator]:
        cls._registry[generator_type.type_name] = generator_type
        return generator_type

    def _key(self, entity_id: str, deck_id: str) -> CardKey:
        if entity_id not in self.target_ids:
            raise PresentationError(
                f"generator {self.id!r} does not generate an exercise for entity {entity_id!r}"
            )
        return CardKey.exercise(deck_id, entity_id)

    def generate_card(self, card_key: CardKey, context: ExerciseGeneratorContext) -> Exercise:
        """Generate the semantic exercise identified by one scheduled card key."""

        return self.generate(card_key.entity_id, context)

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
    groups: tuple[EntityGroup, ...] = ()
    exercises: tuple[ExerciseGenerator, ...]
    daily_limits: DailyLimits = Field(default_factory=DailyLimits)
    scheduling: DeckSchedulingSettings = Field(
        default_factory=DeckSchedulingSettings,
        validation_alias=AliasChoices("scheduling", "queue_settings"),
    )

    @property
    def queue_settings(self) -> DeckSchedulingSettings:
        """Return scheduling defaults using queue terminology."""

        return self.scheduling

    @classmethod
    def parse_raw(cls, b: str | bytes | bytearray, *args: Any, **kwargs: Any) -> DeckDocument:
        return cls.model_validate_json(b)

    @classmethod
    def parse_file(cls, path: str | Path, *args: Any, **kwargs: Any) -> DeckDocument:
        return cls.model_validate_json(Path(path).read_bytes())

    @classmethod
    def model_validate_json(
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        extra: Literal["allow", "ignore", "forbid"] | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> DeckDocument:
        return cast(
            DeckDocument,
            _model_validate_unique_json(
                cls,
                json_data,
                strict=strict,
                extra=extra,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            ),
        )

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
        groups = _raw_group_registry(value.get("groups"))
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
            normalized = _expand_generator_group_references(item, runtime_class, groups)
            dispatched.append(runtime_class.model_validate(normalized))
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
        group_ids = tuple(group.id for group in self.groups)
        if len(set(group_ids)) != len(group_ids):
            duplicate = next(item for item in group_ids if group_ids.count(item) > 1)
            raise ValueError(f"duplicate group ID: {duplicate!r}")
        overlap = sorted(set(entity_ids).intersection(group_ids))
        if overlap:
            raise ValueError(f"entity and group IDs must be distinct: {overlap[0]!r}")
        for group in self.groups:
            _require_refs(group.id, group.entities, known, "group member")
        for generator in self.exercises:
            generator.validate_references(known)
        return self


def _raw_group_registry(value: object) -> dict[str, tuple[str, ...]]:
    """Build group aliases early enough to normalize generator envelopes."""

    if not isinstance(value, (list, tuple)):
        return {}
    registry: dict[str, tuple[str, ...]] = {}
    for item in value:
        if isinstance(item, EntityGroup):
            group = item
        elif isinstance(item, Mapping):
            group = EntityGroup.model_validate(item)
        else:
            continue
        if group.id in registry:
            raise ValueError(f"duplicate group ID: {group.id!r}")
        registry[group.id] = group.entities
    return registry


def _expand_entity_list(value: object, groups: Mapping[str, tuple[str, ...]], path: str) -> object:
    """Resolve one whole-list group alias while rejecting mixed list syntax."""

    if isinstance(value, str):
        group_id = value.strip()
        if group_id not in groups:
            raise ValueError(f"{path} must name a known entity group, got {value!r}")
        return list(groups[group_id])
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str) and item.strip() in groups:
                raise ValueError(
                    f"{path} must contain concrete entity IDs; group {item!r} must replace "
                    "the entire list"
                )
    return value


@lru_cache(maxsize=128)
def _generator_annotations(generator_type: type[ExerciseGenerator]) -> dict[str, object]:
    return get_type_hints(generator_type, include_extras=True)


def _expand_generator_group_references(
    item: Mapping[str, object],
    generator_type: type[ExerciseGenerator],
    groups: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    """Resolve aliases according to the registered generator's annotated schema."""

    annotations = _generator_annotations(generator_type)
    return {
        field_name: _resolve_group_references(
            raw_value,
            annotations[field_name],
            groups,
            f"generator {item.get('id')!r} {field_name}",
        )
        if field_name in annotations
        else raw_value
        for field_name, raw_value in item.items()
    }


def _resolve_group_references(
    value: object,
    annotation: object,
    groups: Mapping[str, tuple[str, ...]],
    path: str,
) -> object:
    """Recursively resolve group aliases only at marked entity-list positions."""

    origin = get_origin(annotation)
    if origin is Annotated:
        base, *metadata = get_args(annotation)
        if any(isinstance(item, EntityIdListMarker) for item in metadata):
            return _expand_entity_list(value, groups, path)
        return _resolve_group_references(value, base, groups, path)

    if (
        isinstance(annotation, type)
        and issubclass(annotation, FrozenModel)
        and isinstance(value, Mapping)
    ):
        model_annotations = get_type_hints(annotation, include_extras=True)
        return {
            field_name: _resolve_group_references(
                raw_value,
                model_annotations[field_name],
                groups,
                f"{path}.{field_name}",
            )
            if field_name in model_annotations
            else raw_value
            for field_name, raw_value in value.items()
        }

    args = get_args(annotation)
    if isinstance(value, Mapping) and args and origin is not None:
        value_annotation = args[1] if len(args) > 1 else None
        if value_annotation is not None:
            return {
                key: _resolve_group_references(
                    raw_value, value_annotation, groups, f"{path} for {key!r}"
                )
                for key, raw_value in value.items()
            }

    if isinstance(value, (list, tuple)) and args and origin in (list, tuple):
        item_annotation = args[0]
        return [
            _resolve_group_references(item, item_annotation, groups, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


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

    @property
    def daily_limits(self) -> DailyLimits:
        """Return the validated per-day budgets for this deck."""

        return self.document.daily_limits

    @property
    def scheduling(self) -> DeckSchedulingSettings:
        """Return the validated default queue settings for this deck."""

        return self.document.scheduling

    @property
    def queue_settings(self) -> DeckSchedulingSettings:
        """Alias for callers that describe the settings as queue options."""

        return self.scheduling

    def _generators_by_key(self) -> dict[tuple[str, str | None], ExerciseGenerator]:
        """Choose one stable exercise generator for every scheduled exercise key.

        Sorting by generator ID makes the selected exercise type independent of deck declaration
        order when configurations overlap.
        """

        selected_entities: dict[str, ExerciseGenerator] = {}
        for generator in sorted(self.generators, key=lambda item: item.id):
            for key in generator.scheduled_keys(self.entities):
                selected_entities.setdefault(key[0], generator)
        selected: dict[tuple[str, str | None], ExerciseGenerator] = {}
        for generator in sorted(self.generators, key=lambda item: item.id):
            if generator not in selected_entities.values():
                continue
            for key in generator.scheduled_keys(self.entities):
                if selected_entities.get(key[0]) is generator:
                    selected[key] = generator
        return selected

    @property
    def target_entity_ids(self) -> tuple[str, ...]:
        """The unique entities represented by the deck's scheduled exercises."""

        return tuple(dict.fromkeys(entity_id for entity_id, _cloze_id in self._generators_by_key()))

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
        for (entity_id, _cloze_id), generator in self._generators_by_key().items():
            card_key = CardKey.exercise(self.name, entity_id)
            exercise = generator.generate_card(card_key, context)
            entity_id = exercise.card_key.entity_id
            existing = generated.get(entity_id)
            if existing is not None and existing.card_key != exercise.card_key:
                raise PresentationError("duplicate entity identity between generated exercises")
            generated[entity_id] = exercise
        return generated

    def generate(self, card_key: CardKey, *, rng: random.Random | None = None) -> Exercise:
        selected = self.generator_for_card(card_key)
        context = ExerciseGeneratorContext(self.name, self.entities, rng or random.Random())
        return selected.generate_card(card_key, context)

    def generator_for_card(self, card_key: CardKey) -> ExerciseGenerator:
        """Return the currently selected runtime generator for a stored card key."""

        if card_key.deck_id != self.name:
            raise PresentationError(
                f"card {card_key.deck_id}/{card_key.entity_id} does not belong to deck "
                f"{self.name!r}"
            )
        selected = self._generators_by_key().get((card_key.entity_id, None))
        if selected is None:
            raise PresentationError(
                f"deck {self.name!r} no longer generates card "
                f"{card_key.deck_id}/{card_key.entity_id}"
            )
        return selected

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
    "EntityGroup",
    "ExerciseGenerator",
    "ExerciseGeneratorContext",
]
