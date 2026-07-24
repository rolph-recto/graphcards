"""Registered deck definitions and generated presentation models."""

from rdfcards.decks.analogy import AnalogyDeck, AnalogyPresentation
from rdfcards.decks.base import (
    DEFAULT_MAX_CHOICES,
    DEFAULT_WINDOW_SIZE,
    DeckDefinition,
    Presentation,
)
from rdfcards.decks.basic import BasicDeck, BasicPresentation
from rdfcards.decks.multiple_choice import (
    ChoiceOption,
    MultipleChoiceDeck,
    MultipleChoicePresentation,
)
from rdfcards.decks.ordered_list import (
    OrderedListDeck,
    OrderedListPresentation,
    OrderedListRow,
)

__all__ = [
    "DEFAULT_MAX_CHOICES",
    "DEFAULT_WINDOW_SIZE",
    "AnalogyDeck",
    "AnalogyPresentation",
    "BasicDeck",
    "BasicPresentation",
    "ChoiceOption",
    "DeckDefinition",
    "MultipleChoiceDeck",
    "MultipleChoicePresentation",
    "OrderedListDeck",
    "OrderedListPresentation",
    "OrderedListRow",
    "Presentation",
]
