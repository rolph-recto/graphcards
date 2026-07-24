"""Argparse commands and terminal interaction for GraphCards."""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from fsrs import Rating

from graphcards.app import StudyService
from graphcards.config import AppConfig, load_config
from graphcards.decks import DeckDefinition, Presentation
from graphcards.errors import GraphCardsError, PresentationError
from graphcards.presentation import execute_presentations, load_graph
from graphcards.scaffold import available_templates, initialize_workspace
from graphcards.storage import CardStatus, Repository, datetime_to_text, utc_now
from graphcards.web import run_server


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _card_id(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("must be a 64-character lowercase hexadecimal card ID")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graphcards", description="Learn RDF triples and entities with SPARQL-driven cards"
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
        ("validate", "validate RDF sources and presentation queries"),
        ("sync", "synchronize query results into study state"),
        ("status", "show card counts"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--deck", help="operate on one configured deck")
        if command == "status":
            command_parser.add_argument(
                "--full", action="store_true", help="show card-level schedule details"
            )

    study_parser = subparsers.add_parser("study", help="review due cards")
    study_parser.add_argument("deck", help="configured deck name")
    study_parser.add_argument(
        "--limit",
        type=_nonnegative_int,
        default=20,
        help="maximum cards to review; 0 means unlimited (default: %(default)s)",
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


def _selected_decks(config: AppConfig, name: str | None) -> tuple[DeckDefinition, ...]:
    return (config.deck(name),) if name else config.decks


def _run_validate(config: AppConfig, deck_name: str | None, output: TextIO) -> None:
    graph = load_graph(config.sources)
    for deck in _selected_decks(config, deck_name):
        count = len(execute_presentations(graph, deck))
        print(f"{deck.name}: valid ({count} cards)", file=output)


def _run_sync(config: AppConfig, deck_name: str | None, output: TextIO) -> None:
    graph = load_graph(config.sources)
    with Repository(config.state_path) as repository:
        app = StudyService(graph, repository, config.fsrs.create_scheduler())
        for deck in _selected_decks(config, deck_name):
            active, created = app.sync(deck)
            print(f"{deck.name}: {active} current, {created} new", file=output)


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
            card.card_key.target_kind.value,
            _status_label(card, now),
            card.fsrs_state,
            str(card.review_count),
            datetime_to_text(card.due_at),
            card.suspension_reason or "",
            " ".join(card.card_key.n3_terms),
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
        for index, deck in enumerate(decks):
            if full and index:
                print(file=output)
            status = repository.status(deck.name, now)
            print(
                f"{deck.name}: {status.available} available, "
                f"{status.suspended} suspended, {status.new} new, "
                f"{status.due} due, {status.future} future",
                file=output,
            )
            if full:
                _print_status_table(repository.card_statuses(deck.name), now, output)


def _rate_presentation(
    presentation: Presentation,
    input_fn: Callable[[], str],
    output: TextIO,
    rng: random.Random,
) -> Rating | None:
    """Run the terminal reveal-and-rate interaction shared by every deck kind."""

    def prompt(message: str) -> str:
        print(message, end="", flush=True, file=output)
        return input_fn().strip()

    print(f"\nFront: {presentation.front_text(rng)}", file=output)
    while True:
        answer = prompt("Press Enter to reveal, or q to quit: ")
        if answer.casefold() == "q":
            return None
        if not answer:
            break
        print("Please press Enter to reveal, or q to quit.", file=output)

    print(f"Back:  {presentation.back}", file=output)
    ratings = {"1": Rating.Again, "2": Rating.Hard, "3": Rating.Good, "4": Rating.Easy}
    while True:
        answer = prompt("Rate 1=Again 2=Hard 3=Good 4=Easy, or q to quit: ")
        if answer.casefold() == "q":
            return None
        if answer in ratings:
            return ratings[answer]
        print("Please enter 1, 2, 3, 4, or q.", file=output)


def _run_study(
    config: AppConfig,
    deck_name: str,
    limit: int,
    input_fn: Callable[[], str],
    output: TextIO,
    error: TextIO,
    rng: random.Random,
) -> None:
    deck = config.deck(deck_name)
    graph = load_graph(config.sources)
    with Repository(config.state_path) as repository:
        app = StudyService(graph, repository, config.fsrs.create_scheduler())
        session_time = utc_now()
        app.sync(deck, session_time)
        # Take a stable due-card snapshot for this session. Each presentation is
        # still regenerated immediately before display by app.render().
        cards = repository.due_cards(deck.name, session_time, None if limit == 0 else limit)
        if not cards:
            print("No cards are due.", file=output)
            return
        reviewed = 0
        for card in cards:
            try:
                presentation = app.render(deck, card)
            except PresentationError as presentation_error:
                print(f"Skipping {card.card_id}: {presentation_error}", file=error)
                continue
            rating = _rate_presentation(presentation, input_fn, output, rng)
            if rating is None:
                # No review is persisted until a complete interaction produces a rating.
                print(f"Stopped. Reviewed {reviewed} card(s).", file=output)
                return
            app.review(deck, card, rating, utc_now())
            reviewed += 1
        print(f"Reviewed {reviewed} card(s).", file=output)


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
    print(f"{deck.name}: suspended {card_id}", file=output)


def _run_resume(
    config: AppConfig,
    deck_name: str,
    card_id: str,
    output: TextIO,
) -> None:
    deck = config.deck(deck_name)
    with Repository(config.state_path) as repository:
        repository.resume_card(deck.name, card_id)
    print(f"{deck.name}: resumed {card_id}", file=output)


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[], str] = input,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
    rng: random.Random | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            initialize_workspace(Path(args.directory), args.template)
            directory = Path(args.directory).resolve()
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
        elif args.command == "study":
            _run_study(
                config,
                args.deck,
                args.limit,
                input_fn,
                output,
                error,
                rng or random.Random(),
            )
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
        else:
            print("\nInterrupted; the current card was not reviewed.", file=error)
        return 130
    except EOFError:
        print("\nInput ended; the current card was not reviewed.", file=error)
        return 130
    except (GraphCardsError, OSError, sqlite3.Error) as command_error:
        print(f"error: {command_error}", file=error)
        return 2
