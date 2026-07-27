"""Entity-backed deck aggregates and semantic exercise generators."""

from graphcards.decks.analogy import AnalogyExercise, AnalogyExerciseGenerator
from graphcards.decks.base import (
    Deck,
    DeckDocument,
    Entity,
    ExerciseGenerator,
    ExerciseGeneratorContext,
)
from graphcards.decks.basic import BasicExercise, BasicExerciseGenerator
from graphcards.decks.multiple_choice import (
    MultipleChoiceExercise,
    MultipleChoiceExerciseGenerator,
)
from graphcards.decks.ordered_list import (
    OrderedListExercise,
    OrderedListExerciseGenerator,
)

__all__ = [
    "AnalogyExercise",
    "AnalogyExerciseGenerator",
    "BasicExercise",
    "BasicExerciseGenerator",
    "Deck",
    "DeckDocument",
    "Entity",
    "ExerciseGenerator",
    "ExerciseGeneratorContext",
    "MultipleChoiceExercise",
    "MultipleChoiceExerciseGenerator",
    "OrderedListExercise",
    "OrderedListExerciseGenerator",
]
