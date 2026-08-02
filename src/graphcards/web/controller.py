"""Application controller for the local deck hub."""

from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta
from http import HTTPStatus

from graphcards.app import StudyService
from graphcards.config import AppConfig
from graphcards.decks import Deck, Entity, ExerciseGenerator, ExerciseGeneratorContext
from graphcards.errors import ConfigError, PresentationError
from graphcards.models import CardKey
from graphcards.storage import DeckStatus, Repository, utc_now
from graphcards.web.status import (
    CardReviewView,
    GeneratorRow,
    HistoryRange,
    HistoryView,
    StatusCard,
    card_review_views,
    history_view,
)
from graphcards.web.study import RequestFailure, StudyMode, StudySession


class StudyController:
    """Deck catalog, persistent services, and the optional active session."""

    def __init__(
        self,
        config: AppConfig,
        repository: Repository,
        rng: random.Random,
    ) -> None:
        self.config = config
        self.repository = repository
        self.rng = rng
        self.csrf_token = secrets.token_urlsafe(32)
        self.study_service = StudyService(
            repository,
            config.fsrs.create_scheduler(),
            rng,
        )
        self.session: StudySession | None = None
        sync_time = utc_now()
        for deck in config.decks:
            self.study_service.sync(deck, sync_time)

    def deck_statuses(self) -> tuple[tuple[Deck, DeckStatus], ...]:
        now = utc_now()
        return tuple((deck, self.repository.status(deck.name, now)) for deck in self.config.decks)

    def card_statuses(
        self,
        deck: Deck,
        now: datetime,
    ) -> tuple[StatusCard, ...]:
        """Load active schedules and derive their time-dependent FSRS metric."""

        rows: list[StatusCard] = []
        for status in self.repository.card_statuses(deck.name):
            retrievability = None
            if status.stability is not None and status.last_review_at is not None:
                retrievability = self.study_service.scheduler.get_card_retrievability(
                    status.stored_card().card(),
                    current_datetime=now,
                )
            labels = tuple(
                f"{generator.id} ({generator.type})"
                for generator in deck.generators
                if status.card_key.entity_id in generator.target_ids
            )
            entity = deck.entities.get(status.card_key.entity_id)
            if entity is None:
                entity = Entity(id=status.card_key.entity_id)
            rows.append(
                StatusCard(
                    status=status,
                    entity=entity,
                    retrievability=retrievability,
                    generator_labels=labels,
                )
            )
        return tuple(rows)

    def generator_rows(self, deck: Deck, now: datetime) -> tuple[GeneratorRow, ...]:
        """Describe every configured generator, including generators with no due cards."""

        due_by_generator = {generator.id: 0 for generator in deck.generators}
        for row in self.card_statuses(deck, now):
            if row.status.suspended or row.status.due_at > now:
                continue
            generator_id = deck.generator_for_card(row.status.card_key).id
            if generator_id in due_by_generator:
                due_by_generator[generator_id] += 1
        return tuple(
            GeneratorRow(
                generator_id=generator.id,
                generator_type=generator.type,
                eligible_count=len(generator.scheduled_keys(deck.entities)),
                due_count=due_by_generator[generator.id],
            )
            for generator in deck.generators
        )

    def preview_entity(self, deck: Deck, entity_id: str):
        """Render a random configured exercise for an active card entity."""

        preview_rng = random.Random()
        matching = [
            row
            for row in self.card_statuses(deck, utc_now())
            if row.status.card_key.entity_id == entity_id
        ]
        if not matching:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That card is not known in this deck.")
        generators = tuple(
            generator for generator in deck.generators if entity_id in generator.target_ids
        )
        if not generators:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "That card no longer has an available exercise generator.",
            )
        row = preview_rng.choice(matching)
        generator = deck.generator_for_card(row.status.card_key)
        return self._render_preview(
            deck,
            generator,
            entity_id,
            preview_rng,
        )

    def preview_generator(self, deck: Deck, generator_id: str):
        """Render a random eligible exercise without changing persisted study state."""

        generator = next(
            (candidate for candidate in deck.generators if candidate.id == generator_id),
            None,
        )
        if generator is None:
            raise RequestFailure(
                HTTPStatus.NOT_FOUND, "That exercise generator is not in this deck."
            )
        scheduled_keys = generator.scheduled_keys(deck.entities)
        if not scheduled_keys:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "That exercise generator has no eligible targets.",
            )
        preview_rng = random.Random()
        entity_id, _cloze_id = preview_rng.choice(scheduled_keys)
        return self._render_preview(deck, generator, entity_id, preview_rng)

    def entity_status(self, deck: Deck, entity_id: str, now: datetime) -> StatusCard:
        """Return the current active card for an entity or a safe not-found error."""

        for row in self.card_statuses(deck, now):
            if row.status.card_key.entity_id == entity_id:
                return row
        raise RequestFailure(HTTPStatus.NOT_FOUND, "That card is not known in this deck.")

    def generators_for_entity(
        self,
        deck: Deck,
        entity_id: str,
    ) -> tuple[ExerciseGenerator, ...]:
        """Return configured generators that can produce an entity's exercises."""

        return tuple(
            generator for generator in deck.generators if entity_id in generator.target_ids
        )

    def preview_generator_for_entity(
        self,
        deck: Deck,
        entity_id: str,
        generator_id: str,
    ):
        """Render a non-persistent exercise for one entity-owned generator."""

        self.entity_status(deck, entity_id, utc_now())
        generator = next(
            (
                candidate
                for candidate in self.generators_for_entity(deck, entity_id)
                if candidate.id == generator_id
            ),
            None,
        )
        if generator is None:
            raise RequestFailure(
                HTTPStatus.NOT_FOUND,
                "That exercise generator is not associated with this card.",
            )
        scheduled_keys = tuple(
            key for key in generator.scheduled_keys(deck.entities) if key[0] == entity_id
        )
        if not scheduled_keys:
            raise RequestFailure(
                HTTPStatus.NOT_FOUND,
                "That exercise generator is not associated with this card.",
            )
        selected_entity_id, _cloze_id = random.Random().choice(scheduled_keys)
        return self._render_preview(deck, generator, selected_entity_id, random.Random())

    def _render_preview(
        self,
        deck: Deck,
        generator: ExerciseGenerator,
        entity_id: str,
        rng: random.Random,
    ):
        try:
            context = ExerciseGeneratorContext(deck.name, deck.entities, rng)
            card_key = CardKey.exercise(deck.name, entity_id)
            exercise = generator.generate_card(card_key, context)
            return deck.render(exercise, rng=rng)
        except (PresentationError, KeyError, TypeError, ValueError) as error:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "That exercise preview is no longer available.",
            ) from error

    def card_history(
        self,
        deck: Deck,
        selected_range: HistoryRange,
        now: datetime,
    ) -> HistoryView:
        """Aggregate immutable review events for one deck."""

        records = self.repository.review_history(deck.name, now)
        return history_view(
            records,
            selected_range,
            now,
            self.config.display_timezone,
        )

    def card_review_history(
        self,
        deck: Deck,
        entity_id: str,
        now: datetime,
    ) -> tuple[CardReviewView, ...]:
        """Return every immutable review event for one active card."""

        self.entity_status(deck, entity_id, now)
        records = tuple(
            record
            for record in self.repository.review_history(deck.name, now)
            if record.card_key.entity_id == entity_id
        )
        return card_review_views(records, now, self.config.display_timezone)

    def set_suspension(
        self,
        *,
        csrf_token: str,
        deck_name: str,
        entity_id: str | None = None,
        generator_id: str | None = None,
        suspended: bool,
        reason: str | None = None,
    ) -> None:
        if not secrets.compare_digest(csrf_token, self.csrf_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This card-status form is not valid.")
        try:
            deck = self.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        entity_id = self._resolve_status_card(
            deck,
            entity_id=entity_id,
            generator_id=generator_id,
        )
        if not self.repository.has_membership(deck.name, entity_id) or not (
            self.repository.card_available(deck.name, entity_id)
            or self.repository.card_suspended(deck.name, entity_id)
        ):
            raise RequestFailure(
                HTTPStatus.NOT_FOUND,
                "That card is not known in this deck.",
            )
        if suspended:
            self.study_service.suspend(deck, entity_id, reason)
        else:
            self.study_service.resume(deck, entity_id)
        if self.session is not None and self.session.deck.name == deck.name:
            self.session.refresh_availability()

    def check_csrf(self, csrf_token: str) -> None:
        """Validate a mutating web form without performing a card action."""

        if not secrets.compare_digest(csrf_token, self.csrf_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This card-status form is not valid.")

    def set_suspensions(
        self,
        *,
        csrf_token: str,
        deck_name: str,
        card_keys: tuple[CardKey, ...],
        suspended: bool,
        reason: str | None = None,
    ) -> None:
        """Apply one validated bulk card-status action atomically."""

        if not secrets.compare_digest(csrf_token, self.csrf_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This card-status form is not valid.")
        try:
            deck = self.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        if any(card_key.deck_id != deck.name for card_key in card_keys):
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "One or more selected cards is outside this deck.",
            )
        entity_ids = tuple(card_key.entity_id for card_key in card_keys)
        known = {row.status.card_key.entity_id for row in self.card_statuses(deck, utc_now())}
        if not set(entity_ids).issubset(known):
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "One or more selected cards is no longer available.",
            )
        if suspended:
            self.study_service.suspend_many(deck, entity_ids, reason)
        else:
            self.study_service.resume_many(deck, entity_ids)
        if self.session is not None and self.session.deck.name == deck.name:
            self.session.refresh_availability()

    def _resolve_status_card(
        self,
        deck: Deck,
        *,
        entity_id: str | None,
        generator_id: str | None,
    ) -> str:
        """Resolve a status action to a current active membership."""

        statuses = self.repository.card_statuses(deck.name)
        if entity_id is not None:
            for status in statuses:
                key = status.card_key
                if key.entity_id == entity_id and (
                    generator_id is None or deck.generator_for_card(key).id == generator_id
                ):
                    return entity_id
        raise RequestFailure(HTTPStatus.NOT_FOUND, "That card is not known in this deck.")

    def end_session(self) -> None:
        """End the active study session when the student leaves the study flow."""

        self.session = None

    def start_session(
        self,
        *,
        csrf_token: str,
        deck_name: str,
        mode: StudyMode,
        days: int,
        requested_limit: int,
    ) -> StudySession:
        if not secrets.compare_digest(csrf_token, self.csrf_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This session form is not valid.")
        try:
            deck = self.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.BAD_REQUEST, "That deck is not available.") from error

        now = utc_now()
        limit = None if requested_limit == 0 else requested_limit
        if mode is StudyMode.DUE:
            cards = self.repository.due_cards(deck.name, now, None)
        elif mode is StudyMode.FORGOTTEN:
            cards = self.repository.forgotten_cards(
                deck.name,
                now - timedelta(days=days),
                limit,
            )
        elif mode is StudyMode.PRACTICE:
            cards = self.repository.active_cards(deck.name)
            self.rng.shuffle(cards)
            if limit is not None:
                cards = cards[:limit]
        else:
            cards = self.repository.future_cards(
                deck.name,
                now,
                now + timedelta(days=days),
                limit,
            )
        self.session = StudySession(
            deck,
            self.study_service,
            cards,
            mode,
            days,
            requested_limit,
        )
        return self.session
