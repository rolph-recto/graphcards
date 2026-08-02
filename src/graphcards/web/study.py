"""Stable in-memory browser study sessions."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus

from fsrs import Rating

from graphcards.app import StudyService
from graphcards.decks import Deck
from graphcards.errors import DailyLimitError, PresentationError, StaleReviewError, StorageError
from graphcards.models import CardView
from graphcards.scheduling import DailyUsage, QueueKind, QueuePlan
from graphcards.storage import StoredCard, utc_now


class StudyMode(StrEnum):
    DUE = "due"
    FORGOTTEN = "forgotten"
    PRACTICE = "practice"
    AHEAD = "ahead"

    @property
    def label(self) -> str:
        return {
            StudyMode.DUE: "Due cards",
            StudyMode.FORGOTTEN: "Review forgotten",
            StudyMode.PRACTICE: "Practice deck",
            StudyMode.AHEAD: "Review ahead",
        }[self]


class RequestFailure(Exception):
    """A safe HTTP failure raised by web study state transitions."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class CurrentCard:
    card: StoredCard
    view: CardView
    revealed: bool = False

    @property
    def front(self) -> str:
        return self.view.front

    @property
    def back(self) -> str:
        return self.view.back


class StudySession:
    """Own one stable, sequential browser study session."""

    def __init__(
        self,
        deck: Deck,
        service: StudyService,
        cards: list[StoredCard],
        mode: StudyMode,
        days: int,
        requested_limit: int,
        plan: QueuePlan | None = None,
    ) -> None:
        self.deck = deck
        self.service = service
        self.cards = tuple(cards)
        self.mode = mode
        self.days = days
        self.requested_limit = requested_limit
        self.plan = plan
        self.session_token = secrets.token_urlsafe(32)
        self.index = 0
        self.completed_count = 0
        self.suspended_count = 0
        self.skipped: list[str] = []
        self.current: CurrentCard | None = None
        self._load_current()

    @property
    def complete(self) -> bool:
        return self.current is None

    @property
    def is_practice(self) -> bool:
        return self.mode is StudyMode.PRACTICE

    @property
    def current_queue_label(self) -> str | None:
        """Return the current card's validated queue label."""

        if self.current is None:
            return None
        return self.service.store.queue_kind(self.current.card.card_key).value.title()

    @property
    def current_queue(self) -> QueueKind | None:
        if self.current is None:
            return None
        return self.service.queue_for_card(self.current.card)

    @property
    def daily_usage(self) -> DailyUsage:
        return self.service.daily_usage(self.deck, utc_now())

    @property
    def daily_limit_reached(self) -> bool:
        return self.plan is not None and self.current is None and self.plan.hidden_count > 0

    def _load_current(self) -> None:
        while self.index < len(self.cards):
            card = self.cards[self.index]
            if not self.service.store.card_available(self.deck, card.card_key.entity_id):
                if self.service.store.card_suspended(self.deck, card.card_key.entity_id):
                    self.suspended_count += 1
                self.index += 1
                continue
            try:
                view = self.service.render(self.deck, card)
            except PresentationError as error:
                self.skipped.append(f"{card.card_key.entity_id}: {error}")
                self.index += 1
                continue
            self.current = CurrentCard(
                card=card,
                view=view,
            )
            return
        self.current = None

    def _require_current(
        self,
        session_token: str,
        entity_id: str,
        *,
        refresh: bool = True,
    ) -> CurrentCard:
        if not secrets.compare_digest(session_token, self.session_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This study form is not valid.")
        if refresh:
            self.refresh_availability()
        if self.current is None:
            raise RequestFailure(HTTPStatus.CONFLICT, "This study session is already complete.")
        if entity_id != self.current.card.card_key.entity_id:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "That card is no longer current. Reload the study page and try again.",
            )
        return self.current

    def reveal(self, session_token: str, entity_id: str) -> None:
        current = self._require_current(session_token, entity_id)
        if current.revealed:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "The answer to this card is already revealed.",
            )
        current.revealed = True

    def rate(self, session_token: str, entity_id: str, rating: Rating) -> None:
        # Keep a deleted current card in place long enough for the store's
        # snapshot-safe review path to produce the actionable stale-card error.
        current = self._require_current(session_token, entity_id, refresh=False)
        if self.is_practice:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Practice cards do not update scheduling.",
            )
        if not current.revealed:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Reveal the answer before rating this card.",
            )
        try:
            self.service.review(self.deck, current.card, rating, utc_now())
        except DailyLimitError as error:
            blocked_queues = {QueueKind.NEW} if error.budget == "new" else set(QueueKind)
            self._advance(completed=False)
            while self.current is not None:
                try:
                    current_queue = self.current_queue
                except StorageError:
                    break
                if current_queue not in blocked_queues:
                    break
                self._advance(completed=False)
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                f"The daily {error.budget} limit has been reached. Continue with the next "
                "available queue or return tomorrow.",
            ) from error
        except StaleReviewError as error:
            refreshed = self.service.store.get_card(self.deck, current.card.card_key)
            if refreshed is None:
                self.skipped.append("A card was removed after this study session started.")
                self.index += 1
                self.current = None
                self._load_current()
                message = "This card is no longer available. Continue with the next card."
            else:
                current.card = refreshed
                message = "This card was reviewed elsewhere. Reload the study page and try again."
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                message,
            ) from error
        except StorageError as error:
            if not str(error).startswith("cannot review unavailable entity"):
                raise
            self.refresh_availability()
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "This card is no longer available. Continue with the next card.",
            ) from error
        self._advance()

    def next_practice(self, session_token: str, entity_id: str) -> None:
        current = self._require_current(session_token, entity_id)
        if not self.is_practice:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Only practice sessions use the Next action.",
            )
        if not current.revealed:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Reveal the answer before continuing.",
            )
        self._advance()

    def suspend(self, session_token: str, entity_id: str, reason: str | None) -> None:
        current = self._require_current(session_token, entity_id)
        self.service.suspend(self.deck, current.card.card_key.entity_id, reason)
        self._advance(completed=False, suspended=True)

    def refresh_availability(self) -> None:
        """Drop a current card suspended or removed after session creation."""

        if self.current is None or self.service.store.card_available(
            self.deck,
            self.current.card.card_key.entity_id,
        ):
            return
        self.current = None
        self._load_current()

    def _advance(self, *, completed: bool = True, suspended: bool = False) -> None:
        if completed:
            self.completed_count += 1
        if suspended:
            self.suspended_count += 1
        self.index += 1
        self.current = None
        self._load_current()


def completion_summary(session: StudySession) -> tuple[str, str]:
    if session.cards:
        title = "Session complete"
        verb = "Practiced" if session.is_practice else "Reviewed"
        summary = f"{verb} {session.completed_count} card(s)."
    elif session.mode is StudyMode.DUE:
        title, summary = "You’re all caught up", "No cards are due in this deck."
    elif session.mode is StudyMode.FORGOTTEN:
        title = "No forgotten cards"
        summary = f"No cards were rated Again in the last {session.days} day(s)."
    elif session.mode is StudyMode.PRACTICE:
        title, summary = "Nothing to practice", "This deck has no available cards."
    else:
        title = "Nothing due soon"
        summary = f"No cards are due in the next {session.days} day(s)."
    if session.skipped:
        summary += f" Skipped {len(session.skipped)} card(s) that could not be presented."
    if session.suspended_count:
        summary += f" Suspended {session.suspended_count} card(s)."
    return title, summary
