"""Argparse commands for GraphCards."""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from graphcards.app import StudyService
from graphcards.config import AppConfig, default_config_path, load_config
from graphcards.decks import Deck
from graphcards.errors import GraphCardsError
from graphcards.presentation import execute_cards
from graphcards.scaffold import (
    TEMPLATE_FORMATS,
    available_templates,
    initialize_user_setup,
    initialize_workspace,
)
from graphcards.storage import CardStatus, DeckFileStateStore, datetime_to_text, utc_now
from graphcards.web import run_server


def _entity_id(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must be a non-blank entity ID")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graphcards", description="Learn entity-backed exercises with FSRS scheduling"
    )
    parser.add_argument(
        "-c",
        "--config",
        default=str(default_config_path()),
        help="user-wide GraphCards TOML file (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a deck")
    init_parser.add_argument("directory")
    init_parser.add_argument("--template", help="create a deck from a bundled template")
    init_parser.add_argument(
        "--format",
        dest="deck_format",
        choices=TEMPLATE_FORMATS,
        default="json",
        help="deck format to copy (default: %(default)s)",
    )
    init_parser.add_argument("-c", "--config", dest="config", default=argparse.SUPPRESS)

    templates_parser = subparsers.add_parser("templates", help="list configured templates")
    templates_parser.add_argument("-c", "--config", dest="config", default=argparse.SUPPRESS)

    setup_parser = subparsers.add_parser(
        "setup", help="create the user-wide configuration and template library"
    )
    setup_parser.add_argument("-c", "--config", dest="config", default=argparse.SUPPRESS)

    for command, help_text in (
        ("validate", "validate JSON/TOML/YAML deck study content"),
        ("sync", "synchronize generated exercises into study state"),
        ("status", "show card counts"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text, description=help_text)
        command_parser.add_argument("--deck", help="operate on one configured deck")
        if command == "status":
            command_parser.add_argument(
                "--full", action="store_true", help="show card-level schedule details"
            )

    suspend_parser = subparsers.add_parser(
        "suspend", help="exclude a card from one deck's study queues"
    )
    suspend_parser.add_argument("deck", help="configured deck name")
    suspend_parser.add_argument("entity_id", type=_entity_id, help="entity ID")
    suspend_parser.add_argument("--reason", help="optional current suspension reason")

    resume_parser = subparsers.add_parser(
        "resume", help="return a suspended card to one deck's study queues"
    )
    resume_parser.add_argument("deck", help="configured deck name")
    resume_parser.add_argument("entity_id", type=_entity_id, help="entity ID")

    subparsers.add_parser("serve", help="open the local web study interface")
    return parser


def _selected_decks(config: AppConfig, name: str | None) -> tuple[Deck, ...]:
    return (config.deck(name),) if name else config.decks


def _run_validate(config: AppConfig, deck_name: str | None, output: TextIO) -> None:
    for deck in _selected_decks(config, deck_name):
        count = len(execute_cards(deck))
        print(f"{deck.display_name}: valid ({count} cards)", file=output)


def _run_sync(config: AppConfig, deck_name: str | None, output: TextIO) -> None:
    with DeckFileStateStore(config.decks) as state_store:
        app = StudyService(
            state_store,
            config.fsrs.create_scheduler(),
            display_timezone=config.display_timezone,
        )
        for deck in _selected_decks(config, deck_name):
            active, created = app.sync(deck)
            print(f"{deck.display_name}: {active} current, {created} new", file=output)


def _status_label(card: CardStatus, now: datetime) -> str:
    timing = "due" if card.due_at <= now else "future"
    schedule = f"new/{timing}" if card.review_count == 0 else timing
    return f"suspended/{schedule}" if card.suspended else schedule


def _print_status_table(cards: tuple[CardStatus, ...], now: datetime, output: TextIO) -> None:
    if not cards:
        print("(no current cards)", file=output)
        return
    headers = (
        "TARGET",
        "STATUS",
        "QUEUE",
        "FSRS STATE",
        "REVIEWS",
        "DUE (UTC)",
        "REASON",
        "IDENTITY",
    )
    rows = [
        (
            "entity",
            _status_label(card, now),
            card.queue.value,
            card.fsrs_state,
            str(card.review_count),
            datetime_to_text(card.due_at),
            card.suspension_reason or "",
            " / ".join(card.card_key.identity_parts),
        )
        for card in cards
    ]
    widths = tuple(
        max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)
    )
    print(
        "  ".join(header.ljust(width) for header, width in zip(headers, widths, strict=True)),
        file=output,
    )
    print("  ".join("-" * width for width in widths), file=output)
    for row in rows:
        print(
            "  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)),
            file=output,
        )


def _run_status(config: AppConfig, deck_name: str | None, full: bool, output: TextIO) -> None:
    now = utc_now()
    with DeckFileStateStore(config.decks) as state_store:
        decks = _selected_decks(config, deck_name)
        service = StudyService(
            state_store,
            config.fsrs.create_scheduler(),
            display_timezone=config.display_timezone,
        )
        for deck in decks:
            service.sync(deck, now)
        for index, deck in enumerate(decks):
            if full and index:
                print(file=output)
            status = state_store.queue_status(
                deck,
                now,
                config.display_timezone,
                service.daily_limits(deck),
            )
            print(
                f"{deck.display_name}: {status.available} available, "
                f"{status.suspended} suspended, {status.new} new, "
                f"{status.due} due, {status.future} future",
                file=output,
            )
            print(
                "  queues: "
                f"learning {status.queue_counts.learning}, "
                f"relearning {status.queue_counts.relearning}, "
                f"review {status.queue_counts.review}, "
                f"new {status.queue_counts.new} "
                f"({status.studyable_due} available today)",
                file=output,
            )
            print(
                "  daily: "
                f"new {status.daily_usage.new_used}/{status.daily_usage.new_limit} "
                f"({status.daily_usage.new_remaining} remaining), "
                f"reviews {status.daily_usage.reviews_used}/"
                f"{status.daily_usage.reviews_limit} "
                f"({status.daily_usage.reviews_remaining} remaining)",
                file=output,
            )
            print(
                "  hidden by daily limit: "
                f"learning {status.hidden_counts.learning}, "
                f"relearning {status.hidden_counts.relearning}, "
                f"review {status.hidden_counts.review}, "
                f"new {status.hidden_counts.new}",
                file=output,
            )
            if full:
                _print_status_table(state_store.card_statuses(deck), now, output)


def _run_suspend(
    config: AppConfig,
    deck_name: str,
    entity_id: str,
    reason: str | None,
    output: TextIO,
) -> None:
    deck = config.deck(deck_name)
    with DeckFileStateStore(config.decks) as state_store:
        state_store.suspend_card(deck, entity_id, reason)
    print(f"{deck.display_name}: suspended {entity_id}", file=output)


def _run_resume(
    config: AppConfig,
    deck_name: str,
    entity_id: str,
    output: TextIO,
) -> None:
    deck = config.deck(deck_name)
    with DeckFileStateStore(config.decks) as state_store:
        state_store.resume_card(deck, entity_id)
    print(f"{deck.display_name}: resumed {entity_id}", file=output)


def main(
    argv: Sequence[str] | None = None,
    *,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
    rng: random.Random | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            config_path = initialize_user_setup(Path(args.config))
            print(f"Created user-wide GraphCards setup in {config_path.parent}", file=output)
            return 0

        if args.command == "init":
            config = load_config(args.config)
            directory = initialize_workspace(
                Path(args.directory),
                args.template,
                args.deck_format,
                config.templates_paths,
            )
            if args.template:
                print(
                    f"Created GraphCards deck from template {args.template!r} "
                    f"({args.deck_format}) in {directory}",
                    file=output,
                )
            else:
                print(f"Created empty GraphCards directory in {directory}", file=output)
            return 0

        if args.command == "templates":
            config = load_config(args.config)
            for name in available_templates(config.templates_paths):
                print(name, file=output)
            return 0

        config = load_config(args.config)
        if args.command == "validate":
            _run_validate(config, args.deck, output)
        elif args.command == "sync":
            _run_sync(config, args.deck, output)
        elif args.command == "status":
            _run_status(config, args.deck, args.full, output)
        elif args.command == "suspend":
            _run_suspend(config, args.deck, args.entity_id, args.reason, output)
        elif args.command == "resume":
            _run_resume(config, args.deck, args.entity_id, output)
        elif args.command == "serve":
            run_server(
                config,
                output=output,
                error=error,
                rng=rng or random.Random(),
            )
        return 0
    except KeyboardInterrupt:
        if args.command == "serve":
            print("\nWeb server stopped.", file=error)
        return 130
    except (GraphCardsError, OSError) as command_error:
        print(f"error: {command_error}", file=error)
        return 2
