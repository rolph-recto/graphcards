"""Study-session orchestration across RDFLib, SQLite, and FSRS."""

from __future__ import annotations

from datetime import datetime

from fsrs import Rating, Scheduler
from rdflib import Graph

from rdfcards.config import DeckDefinition
from rdfcards.decks import DeckKind
from rdfcards.errors import PresentationError
from rdfcards.presentation import execute_presentations
from rdfcards.storage import Repository, StoredCard, datetime_as_utc, utc_now


class StudyService:
    """Coordinate graph rendering, persistent state, and FSRS reviews."""

    def __init__(
        self,
        graph: Graph,
        repository: Repository,
        scheduler: Scheduler,
    ) -> None:
        self.graph = graph
        self.repository = repository
        self.scheduler = scheduler

    def sync(self, deck: DeckDefinition, now: datetime | None = None) -> tuple[int, int]:
        presentations = execute_presentations(self.graph, deck)
        return self.repository.sync_deck(deck.name, presentations, now or utc_now())

    def render(self, deck: DeckDefinition, card: StoredCard) -> DeckKind:
        presentations = execute_presentations(self.graph, deck, card.card_key)
        presentation = presentations.get(card.card_id)
        if presentation is None:
            raise PresentationError(f"deck {deck.name!r} no longer renders card {card.card_id}")
        return presentation

    def review(
        self,
        deck: DeckDefinition,
        card: StoredCard,
        rating: Rating,
        now: datetime | None = None,
    ) -> StoredCard:
        if card.card_key.target_kind != deck.target:
            raise PresentationError(
                f"deck {deck.name!r} targets {deck.target} cards but received a "
                f"{card.card_key.target_kind} card"
            )
        review_time = datetime_as_utc(now or utc_now())
        updated_card, review_log = self.scheduler.review_card(
            card.card(), rating, review_datetime=review_time
        )
        self.repository.save_review(card.card_id, deck.name, updated_card, review_log)
        # Reload the committed representation rather than returning an FSRS object
        # that might differ from what storage accepted.
        stored = self.repository.get_card(card.card_id)
        if stored is None:
            raise RuntimeError("reviewed card disappeared from storage")
        return stored
