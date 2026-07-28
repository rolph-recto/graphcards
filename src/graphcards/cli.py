"""Argparse commands for GraphCards."""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from graphcards.app import StudyService
from graphcards.config import AppConfig, load_config
from graphcards.decks import Deck
from graphcards.errors import GraphCardsError
from graphcards.presentation import execute_cards
from graphcards.scaffold import available_templates, initialize_workspace
from graphcards.storage import CardStatus, Repository, datetime_to_text, utc_now
from graphcards.web import run_server


def _card_id(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("must be a 64-character lowercase hexadecimal card ID")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graphcards", description="Learn entity-backed exercises with FSRS scheduling"
    )
    parser.add_argument(
        "-c", "--config", default="graphcards.toml", help="project TOML file (default: %(default)s)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a study workspace")
    init_parser.add_argument("directory")
    init_parser.add_argument("--template", help="create a bundled workspace template")

    subparsers.add_parser("templates", help="list bundled workspace templates")

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
    suspend_parser.add_argument("card_id", type=_card_id, help="full card ID from status --full")
    suspend_parser.add_argument("--reason", help="optional current suspension reason")

    resume_parser = subparsers.add_parser(
        "resume", help="return a suspended card to one deck's study queues"
    )
    resume_parser.add_argument("deck", help="configured deck name")
    resume_parser.add_argument("card_id", type=_card_id, help="full card ID from status --full")

    subparsers.add_parser("serve", help="open the local web study interface")
    return parser


def _selected_decks(config: AppConfig, name: str | None) -> tuple[Deck, ...]:
    return (config.deck(name),) if name else config.decks


def _run_validate(config: AppConfig, deck_name: str | None, output: TextIO) -> None:
    for deck in _selected_decks(config, deck_name):
        count = len(execute_cards(deck))
        print(f"{deck.display_name}: valid ({count} cards)", file=output)


def _run_sync(config: AppConfig, deck_name: str | None, output: TextIO) -> None:
    with Repository(config.state_path) as repository:
        app = StudyService(repository, config.fsrs.create_scheduler())
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
        "CARD ID",
        "TARGET",
        "STATUS",
        "FSRS STATE",
        "REVIEWS",
        "DUE (UTC)",
        "REASON",
        "IDENTITY",
    )
    rows = [
        (
            card.card_id,
            "entity",
            _status_label(card, now),
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
    with Repository(config.state_path) as repository:
        decks = _selected_decks(config, deck_name)
        service = StudyService(repository, config.fsrs.create_scheduler())
        for deck in decks:
            service.sync(deck, now)
        for index, deck in enumerate(decks):
            if full and index:
                print(file=output)
            status = repository.status(deck.name, now)
            print(
                f"{deck.display_name}: {status.available} available, "
                f"{status.suspended} suspended, {status.new} new, "
                f"{status.due} due, {status.future} future",
                file=output,
            )
            if full:
                _print_status_table(repository.card_statuses(deck.name), now, output)


def _run_suspend(
    config: AppConfig,
    deck_name: str,
    card_id: str,
    reason: str | None,
    output: TextIO,
) -> None:
    deck = config.deck(deck_name)
    with Repository(config.state_path) as repository:
        repository.suspend_card(deck.name, card_id, reason)
    print(f"{deck.display_name}: suspended {card_id}", file=output)


def _run_resume(
    config: AppConfig,
    deck_name: str,
    card_id: str,
    output: TextIO,
) -> None:
    deck = config.deck(deck_name)
    with Repository(config.state_path) as repository:
        repository.resume_card(deck.name, card_id)
    print(f"{deck.display_name}: resumed {card_id}", file=output)


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
        if args.command == "init":
            directory = initialize_workspace(Path(args.directory), args.template)
            if args.template:
                print(
                    f"Created GraphCards workspace from template {args.template!r} in {directory}",
                    file=output,
                )
            else:
                print(f"Created empty GraphCards workspace in {directory}", file=output)
            return 0

        if args.command == "templates":
            for name in available_templates():
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
            _run_suspend(config, args.deck, args.card_id, args.reason, output)
        elif args.command == "resume":
            _run_resume(config, args.deck, args.card_id, output)
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
    except (GraphCardsError, OSError, sqlite3.Error) as command_error:
        print(f"error: {command_error}", file=error)
        return 2
