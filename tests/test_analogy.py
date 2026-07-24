from __future__ import annotations

import io
import random
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdflib import Graph, Literal, URIRef

from rdfcards.app import StudyService
from rdfcards.cli import _rate_presentation
from rdfcards.config import FsrsSettings, load_config
from rdfcards.decks import (
    AnalogyDeck,
    AnalogyPresentation,
    DeckDefinition,
    Presentation,
)
from rdfcards.errors import ConfigError, PresentationError
from rdfcards.models import CardKey, TargetKind
from rdfcards.presentation import execute_presentations
from rdfcards.storage import Repository

PREFIX = """
PREFIX ex: <https://example.org/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


def run_query(tmp_path: Path, query: str) -> dict[str, Presentation]:
    query_path = tmp_path / "analogy.rq"
    query_path.write_text(PREFIX + query, encoding="utf-8")
    deck = AnalogyDeck(
        name="analogy",
        target=TargetKind.TRIPLE,
        query_path=query_path,
    )
    return execute_presentations(Graph(), deck)


def test_analogy_hides_target_object_and_keeps_target_identity(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object")
          }
        }
        """,
    )

    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, AnalogyPresentation)
    assert presentation.card_key == CardKey.triple(
        URIRef("https://example.org/France"),
        URIRef("https://example.org/capital"),
        URIRef("https://example.org/Paris"),
    )
    assert presentation.front == Literal(
        "https://example.org/Germany : https://example.org/Berlin :: https://example.org/France : ?"
    )
    assert presentation.back == URIRef("https://example.org/Paris")
    assert presentation.source_subject == URIRef("https://example.org/Germany")
    assert presentation.source_object == URIRef("https://example.org/Berlin")
    assert presentation.hide == Literal("object")


def test_analogy_hides_target_subject_and_uses_display_labels(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
               ?subject_label ?predicate_label ?object_label
               ?source_subject_label ?source_predicate_label ?source_object_label
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
                  ?subject_label ?predicate_label ?object_label
                  ?source_subject_label ?source_predicate_label ?source_object_label
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "subject"
             "France" "capital of" "Paris" "Germany" "capital of" "Berlin")
          }
        }
        """,
    )

    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, AnalogyPresentation)
    assert presentation.front == Literal("Germany capital of Berlin :: ? capital of Paris")
    assert presentation.back == Literal("France")


def test_analogy_uses_effective_predicate_label_when_source_label_differs(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
               ?predicate_label ?source_predicate_label
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
            ?predicate_label ?source_predicate_label
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object"
             "capital of" "is capital of")
          }
        }
        """,
    )

    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, AnalogyPresentation)
    assert presentation.front == Literal(
        "https://example.org/Germany capital of https://example.org/Berlin :: "
        "https://example.org/France capital of ?"
    )


def test_each_target_triple_is_one_card_and_source_is_not_a_card(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object")
            (ex:Spain ex:capital ex:Madrid ex:Italy ex:capital ex:Rome "object")
          }
        }
        """,
    )

    assert set(presentations) == {
        CardKey.triple(
            URIRef("https://example.org/France"),
            URIRef("https://example.org/capital"),
            URIRef("https://example.org/Paris"),
        ).digest,
        CardKey.triple(
            URIRef("https://example.org/Spain"),
            URIRef("https://example.org/capital"),
            URIRef("https://example.org/Madrid"),
        ).digest,
    }


def test_analogy_sync_schedules_only_target_triples(tmp_path: Path) -> None:
    query_path = tmp_path / "analogy.rq"
    query_path.write_text(
        PREFIX
        + """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object")
          }
        }
        """,
        encoding="utf-8",
    )
    deck = AnalogyDeck(
        name="analogy",
        target=TargetKind.TRIPLE,
        query_path=query_path,
    )
    target = CardKey.triple(
        URIRef("https://example.org/France"),
        URIRef("https://example.org/capital"),
        URIRef("https://example.org/Paris"),
    )
    source = CardKey.triple(
        URIRef("https://example.org/Germany"),
        URIRef("https://example.org/capital"),
        URIRef("https://example.org/Berlin"),
    )

    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(Graph(), repository, FsrsSettings().create_scheduler())
        service.sync(deck)

        assert repository.get_card(target.digest) is not None
        assert repository.get_card(source.digest) is None
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
        assert repository.connection.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            '(ex:France ex:capital ex:Paris ex:France ex:capital ex:Paris "object")',
            "source triple must be distinct",
        ),
        (
            '(ex:France ex:capital ex:Paris ex:Germany ex:country ex:Berlin "object")',
            "predicates must match",
        ),
        (
            "(ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin ex:object)",
            "literal with value subject or object",
        ),
        (
            '(ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "answer")',
            "literal with value subject or object",
        ),
        (
            '(ex:France ex:capital UNDEF ex:Germany ex:capital ex:Berlin "object")',
            r"unbound required variables: \?object",
        ),
        (
            '(ex:France ex:capital ex:Paris ex:Germany ex:capital UNDEF "object")',
            r"unbound required variables: \?source_object",
        ),
    ],
)
def test_analogy_rejects_invalid_rows(tmp_path: Path, row: str, message: str) -> None:
    with pytest.raises(PresentationError, match=message):
        run_query(
            tmp_path,
            f"""
            SELECT ?subject ?predicate ?object ?source_subject ?source_predicate
                   ?source_object ?hide
            WHERE {{
              VALUES (
                ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
              ) {{ {row} }}
            }}
            """,
        )


def test_analogy_rejects_conflicting_duplicate_source_or_display_values(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="conflicting analogy source"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?predicate ?object ?source_subject ?source_predicate
                   ?source_object ?hide
                   ?subject_label
            WHERE {
              VALUES (
                ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object
                ?hide ?subject_label
              ) {
                (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object"
                 "France")
                (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object"
                 "French Republic")
              }
            }
            """,
        )


def test_analogy_deduplicates_equivalent_literal_spellings(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
               ?subject_label
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object
            ?hide ?subject_label
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object" "France")
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin
             "object"^^xsd:string "France"^^xsd:string)
          }
        }
        """,
    )

    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, AnalogyPresentation)
    assert presentation.hide == Literal("object")
    assert str(presentation.back) == "https://example.org/Paris"


def test_analogy_deduplicates_explicit_label_equal_to_term_fallback(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
               ?subject_label
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object
            ?hide ?subject_label
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object" UNDEF)
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object"
             "https://example.org/France")
          }
        }
        """,
    )

    assert len(presentations) == 1


def test_analogy_deduplicates_display_equivalent_language_labels(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
               ?object_label
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object
            ?hide ?object_label
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object" "Paris"@en)
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object" "Paris"@fr)
          }
        }
        """,
    )

    assert len(presentations) == 1


def test_analogy_distinguishes_sources_with_the_same_display_text(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="conflicting analogy source"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?predicate ?object ?source_subject ?source_predicate
                   ?source_object ?hide ?source_subject_label ?source_object_label
            WHERE {
              VALUES (
                ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object
                ?hide ?source_subject_label ?source_object_label
              ) {
                (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object"
                 "Country" "Capital")
                (ex:France ex:capital ex:Paris ex:Italy ex:capital ex:Rome "object"
                 "Country" "Capital")
              }
            }
            """,
        )


def test_analogy_accepts_xsd_string_hide_literal(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
        WHERE {
          VALUES (
            ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
          ) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin
             "object"^^xsd:string)
          }
        }
        """,
    )
    assert len(presentations) == 1


def test_analogy_uses_generic_cli_reveal_and_rate_flow() -> None:
    target = CardKey.triple(
        URIRef("https://example.org/France"),
        URIRef("https://example.org/capital"),
        URIRef("https://example.org/Paris"),
    )
    presentation = AnalogyPresentation(
        card_key=target,
        front=Literal("Germany capital of Berlin :: France capital of ?"),
        back=Literal("Paris"),
        source_subject=URIRef("https://example.org/Germany"),
        source_predicate=URIRef("https://example.org/capital"),
        source_object=URIRef("https://example.org/Berlin"),
        hide=Literal("object"),
        subject_label=Literal("France"),
        predicate_label=Literal("capital of"),
        object_label=Literal("Paris"),
        source_subject_label=Literal("Germany"),
        source_predicate_label=Literal("capital of"),
        source_object_label=Literal("Berlin"),
    )
    output = io.StringIO()
    answers = iter(("", "3"))

    assert _rate_presentation(presentation, lambda: next(answers), output, random.Random(0))
    snapshots = output.getvalue()
    assert "Front: Germany capital of Berlin :: France capital of ?" in snapshots
    assert "Back:  Paris" in snapshots


def test_analogy_configuration_requires_triple_target(tmp_path: Path) -> None:
    path = tmp_path / "rdfcards.toml"
    path.write_text(
        '[[decks]]\nname="analogy"\ntarget="entity"\nkind="analogy"\nquery="query.rq"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="analogy decks must target triple cards"):
        load_config(path)


def test_analogy_is_registered_as_a_deck_definition() -> None:
    assert DeckDefinition.from_name("analogy") is AnalogyDeck


def test_analogy_direct_validation_rejects_non_literal_hide() -> None:
    with pytest.raises(ValidationError, match="literal with value subject or object"):
        AnalogyPresentation(
            card_key=CardKey.triple(
                URIRef("https://example.org/France"),
                URIRef("https://example.org/capital"),
                URIRef("https://example.org/Paris"),
            ),
            front=Literal("front"),
            back=Literal("back"),
            source_subject=URIRef("https://example.org/Germany"),
            source_predicate=URIRef("https://example.org/capital"),
            source_object=URIRef("https://example.org/Berlin"),
            hide=URIRef("https://example.org/object"),
        )
