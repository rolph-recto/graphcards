"""Image occlusion exercise generator."""

from __future__ import annotations

from typing import ClassVar, Literal
from urllib.parse import quote

from pydantic import Field, StrictStr, model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise, FrozenModel
from graphcards.references import EntityId

FRONT_TEMPLATE = (
    '<figure class="image-occlusion"><div class="image-occlusion__canvas">'
    '<img src="{{ image_url|e }}" alt="{{ image_alt|e }}">'
    '<svg class="image-occlusion__mask-layer" viewBox="0 0 100 100" '
    'preserveAspectRatio="none" role="img" aria-label="Hidden answer">'
    '<rect class="image-occlusion__mask" x="{{ placement.left|e }}" '
    'y="{{ placement.top|e }}" width="{{ placement.width|e }}" '
    'height="{{ placement.height|e }}"></rect>'
    '<text class="image-occlusion__mask-text" '
    'x="{{ placement.left + (placement.width / 2) }}" '
    'y="{{ placement.top + (placement.height / 2) }}">?</text>'
    "</svg></div></figure>"
)
BACK_TEMPLATE = """
<p class="image-occlusion__answer-text">
  {{ target.answer|default(target.label)|default(target.back)|default(target.id)|e }}
</p>
""".strip()


class ImageOcclusionPlacement(FrozenModel):
    """One normalized rectangular target region in an image."""

    target_id: EntityId
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> ImageOcclusionPlacement:
        if self.x + self.width > 1:
            raise ValueError("occlusion x plus width must be at most 1")
        if self.y + self.height > 1:
            raise ValueError("occlusion y plus height must be at most 1")
        return self

    @property
    def left(self) -> float:
        return self.x * 100

    @property
    def top(self) -> float:
        return self.y * 100

    @property
    def percentage_width(self) -> float:
        return self.width * 100

    @property
    def percentage_height(self) -> float:
        return self.height * 100


class _RenderedImageOcclusionPlacement(FrozenModel):
    """Percentage geometry exposed to the HTML template."""

    left: float
    top: float
    width: float
    height: float


@ExerciseGenerator.register
class ImageOcclusionExerciseGenerator(ExerciseGenerator):
    """Generate one card for each target rectangle in one deck-relative image."""

    type: Literal["image_occlusion"] = "image_occlusion"
    type_name = "image_occlusion"
    image_path: StrictStr = Field(min_length=1)
    image_alt: StrictStr = Field(default="Image occlusion")
    occlusions: tuple[ImageOcclusionPlacement, ...] = Field(min_length=1)
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {"image_url", "image_alt", "target", "placement"}
    )

    @model_validator(mode="after")
    def validate_image_path(self) -> ImageOcclusionExerciseGenerator:
        path = self.image_path.strip()
        if not path:
            raise ValueError("image_path must be a non-blank relative path")
        if "\\" in path or path.startswith("/") or ":" in path.split("/", 1)[0]:
            raise ValueError("image_path must be a deck-relative path")
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("image_path must not contain empty, dot, or parent path parts")
        return self

    @model_validator(mode="after")
    def validate_occlusions(self) -> ImageOcclusionExerciseGenerator:
        target_ids = tuple(occlusion.target_id for occlusion in self.occlusions)
        if len(target_ids) != len(set(target_ids)):
            raise ValueError(f"generator {self.id!r} has duplicate occlusion target IDs")
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        _require_refs(self.id, self.target_ids, known_entity_ids, "target entity")

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(occlusion.target_id for occlusion in self.occlusions)

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> ImageOcclusionExercise:
        key = self._key(entity_id, context.deck_id)
        return ImageOcclusionExercise(
            card_key=key,
            generator_id=self.id,
            target_id=entity_id,
            occlusions=self.occlusions,
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, ImageOcclusionExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            target = context.entities[exercise.target_id]
            placement = next(
                item for item in exercise.occlusions if item.target_id == exercise.target_id
            )
        except (KeyError, StopIteration, TypeError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise references an unknown target"
            ) from error
        image_url = (
            f"/decks/{quote(context.deck_id, safe='')}/assets/{quote(self.image_path, safe='/')}"
        )
        rendered_placement = _RenderedImageOcclusionPlacement(
            left=placement.left,
            top=placement.top,
            width=placement.percentage_width,
            height=placement.percentage_height,
        )
        template_context = {
            "image_url": image_url,
            "image_alt": self.image_alt,
            "target": target,
            "placement": rendered_placement,
        }
        return CardView(
            card_key=exercise.card_key,
            front=_render_template(self.front_template or FRONT_TEMPLATE, template_context),
            back=_render_template(self.back_template or BACK_TEMPLATE, template_context),
        )


class ImageOcclusionExercise(Exercise):
    """One target card with the complete image placement set."""

    occlusions: tuple[ImageOcclusionPlacement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target_placement(self) -> ImageOcclusionExercise:
        target_ids = tuple(occlusion.target_id for occlusion in self.occlusions)
        if self.target_id not in target_ids:
            raise ValueError("exercise target ID must have an image occlusion placement")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("exercise occlusions must have unique target IDs")
        return self


__all__ = [
    "ImageOcclusionExercise",
    "ImageOcclusionExerciseGenerator",
    "ImageOcclusionPlacement",
]
