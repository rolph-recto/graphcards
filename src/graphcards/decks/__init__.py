"""Entity-backed deck aggregates and semantic exercise generators."""

from graphcards.decks.analogy import AnalogyExercise, AnalogyExerciseGenerator
from graphcards.decks.base import (
    Deck,
    DeckDocument,
    Entity,
    EntityGroup,
    ExerciseGenerator,
    ExerciseGeneratorContext,
)
from graphcards.decks.basic import BasicExercise, BasicExerciseGenerator
from graphcards.decks.cloze import ClozeExercise, ClozeExerciseGenerator, ClozeSelection
from graphcards.decks.common_relation import (
    CommonRelationExercise,
    CommonRelationExerciseGenerator,
)
from graphcards.decks.missing_sequence_item import (
    MissingSequenceItemExercise,
    MissingSequenceItemExerciseGenerator,
)
from graphcards.decks.multiple_choice import (
    MultipleChoiceExercise,
    MultipleChoiceExerciseGenerator,
)
from graphcards.decks.odd_one_out import (
    OddOneOutExercise,
    OddOneOutExerciseGenerator,
    OddOneOutRelation,
)
from graphcards.decks.scrambled_list import (
    ScrambledListExercise,
    ScrambledListExerciseGenerator,
)
from graphcards.decks.temporal_comparison import (
    TemporalComparisonExercise,
    TemporalComparisonExerciseGenerator,
)
from graphcards.references import EntityId, EntityIdList, EntityIdListMarker

__all__ = [
    "AnalogyExercise",
    "AnalogyExerciseGenerator",
    "BasicExercise",
    "BasicExerciseGenerator",
    "CommonRelationExercise",
    "CommonRelationExerciseGenerator",
    "ClozeExercise",
    "ClozeExerciseGenerator",
    "ClozeSelection",
    "Deck",
    "DeckDocument",
    "Entity",
    "EntityGroup",
    "EntityId",
    "EntityIdList",
    "EntityIdListMarker",
    "ExerciseGenerator",
    "ExerciseGeneratorContext",
    "MultipleChoiceExercise",
    "MultipleChoiceExerciseGenerator",
    "MissingSequenceItemExercise",
    "MissingSequenceItemExerciseGenerator",
    "OddOneOutExercise",
    "OddOneOutExerciseGenerator",
    "OddOneOutRelation",
    "ScrambledListExercise",
    "ScrambledListExerciseGenerator",
    "TemporalComparisonExercise",
    "TemporalComparisonExerciseGenerator",
]
