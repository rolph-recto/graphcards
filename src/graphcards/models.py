"""Immutable domain models for RDF-backed cards and rendered views."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, model_validator
from rdflib import BNode, Literal, URIRef
from rdflib.term import Identifier
from rdflib.util import from_n3

from graphcards.errors import PresentationError, StorageError


class TargetKind(StrEnum):
    TRIPLE = "triple"
    ENTITY = "entity"


def validation_message(error: ValidationError) -> str:
    """Return the first Pydantic failure without implementation-specific decoration."""

    message = str(error.errors(include_url=False)[0]["msg"])
    return message.removeprefix("Value error, ")


class RdfModel(BaseModel):
    """Frozen Pydantic base that permits RDFLib term objects."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)


class FrozenModel(BaseModel):
    """Immutable, strict base for user configuration models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


def resolve_config_path(value: object, info: ValidationInfo) -> Path:
    """Resolve a configured path relative to its TOML file."""

    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("must be a non-empty file path")
    path = Path(value).expanduser()
    context = info.context if isinstance(info.context, dict) else {}
    base = context.get("base")
    if not path.is_absolute() and isinstance(base, Path):
        path = base / path
    return path.resolve()


class CardKey(RdfModel):
    """A validated global identity for one triple- or entity-backed FSRS card."""

    target_kind: TargetKind
    terms: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_identity(self) -> CardKey:
        if self.target_kind is TargetKind.ENTITY:
            if len(self.terms) != 1 or not isinstance(self.terms[0], URIRef):
                raise ValueError("a learnable entity must be identified by one IRI")
            return self
        if len(self.terms) != 3:
            raise ValueError("a triple card must contain exactly three RDF terms")
        subject, predicate, object_ = self.terms
        if isinstance(subject, BNode) or isinstance(object_, BNode):
            raise ValueError(
                "learnable triples cannot contain blank nodes; replace them with stable IRIs"
            )
        if not isinstance(subject, URIRef):
            raise ValueError("a learnable triple subject must be an IRI")
        if not isinstance(predicate, URIRef):
            raise ValueError("a learnable triple predicate must be an IRI")
        if not isinstance(object_, (URIRef, Literal)):
            raise ValueError("a learnable triple object must be an IRI or literal")
        return self

    @classmethod
    def _create(cls, target: TargetKind, terms: tuple[Identifier, ...]) -> CardKey:
        try:
            return cls(target_kind=target, terms=terms)
        except ValidationError as error:
            # Query results are a presentation concern; callers should not need to
            # understand Pydantic's error representation.
            raise PresentationError(validation_message(error)) from error

    @classmethod
    def triple(cls, subject: Identifier, predicate: Identifier, object_: Identifier) -> CardKey:
        return cls._create(TargetKind.TRIPLE, (subject, predicate, object_))

    @classmethod
    def entity(cls, entity: Identifier) -> CardKey:
        return cls._create(TargetKind.ENTITY, (entity,))

    @classmethod
    def from_bindings(cls, target: TargetKind, values: Mapping[str, Identifier]) -> CardKey:
        if target is TargetKind.ENTITY:
            return cls.entity(values["entity"])
        return cls.triple(values["subject"], values["predicate"], values["object"])

    @property
    def n3_terms(self) -> tuple[str, ...]:
        return tuple(term.n3() for term in self.terms)

    @property
    def digest(self) -> str:
        # Domain separation prevents an entity IRI from colliding with a triple
        # containing the same lexical value. Length prefixes preserve term boundaries.
        digest = sha256(f"graphcards:{self.target_kind.value}:v1\0".encode())
        for value in self.n3_terms:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    @property
    def query_bindings(self) -> dict[str, Identifier]:
        if self.target_kind is TargetKind.ENTITY:
            return {"entity": self.terms[0]}
        return dict(zip(("subject", "predicate", "object"), self.terms, strict=True))

    @classmethod
    def from_n3(cls, target: TargetKind, values: tuple[str, ...]) -> CardKey:
        """Reconstruct an identity from storage and report corruption consistently."""

        try:
            terms = tuple(from_n3(value) for value in values)
        except Exception as error:
            raise StorageError("stored card identity contains an invalid N3 term") from error
        if any(term is None for term in terms):
            raise StorageError("stored card identity contains an invalid N3 term")
        try:
            return cls(target_kind=target, terms=terms)  # type: ignore[arg-type]
        except ValidationError as error:
            message = validation_message(error)
            raise StorageError(f"stored card identity is invalid: {message}") from error


class Card(RdfModel):
    """Validated semantic data for one regenerable card."""

    card_key: CardKey


class CardView(RdfModel):
    """Learner-facing strings produced by a stateless presentation renderer."""

    card_key: CardKey
    front: str
    back: str
