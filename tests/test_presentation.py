from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from rdfcards.config import DeckDefinition
from rdfcards.decks import Basic, DeckKind, MultipleChoice
from rdfcards.errors import PresentationError
from rdfcards.models import CardKey, TargetKind
from rdfcards.presentation import execute_presentations

PREFIX = """
PREFIX ex: <https://example.org/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


def run_query(
    tmp_path: Path,
    query: str,
    kind: type[DeckKind] = Basic,
    target: TargetKind = TargetKind.TRIPLE,
) -> dict[str, object]:
    query_path = tmp_path / "query.rq"
    query_path.write_text(PREFIX + query, encoding="utf-8")
    deck = DeckDefinition(
        name="test",
        target=target,
        kind=kind,
        query_path=query_path,
    )
    return execute_presentations(Graph(), deck)


def test_basic_contract_groups_duplicate_rows(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?front ?back WHERE {
          VALUES (?subject ?predicate ?object ?front ?back) {
            (ex:s ex:p ex:o "front" "back")
            (ex:s ex:p ex:o "front" "back")
          }
        }
        """,
    )
    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, Basic)
    assert str(presentation.front) == "front"


def test_query_execution_delegates_to_custom_deck_kind(tmp_path: Path) -> None:
    class CustomBasic(Basic):
        config_name = "custom_basic"

    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?front ?back WHERE {
          VALUES (?subject ?predicate ?object ?front ?back) {
            (ex:s ex:p ex:o "front" "back")
          }
        }
        """,
        CustomBasic,
    )

    assert isinstance(next(iter(presentations.values())), CustomBasic)


def test_multiple_choice_contract(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?front ?choice ?is_correct WHERE {
          VALUES (?subject ?predicate ?object ?front ?choice ?is_correct) {
            (ex:s ex:p ex:o "question" "yes" true)
            (ex:s ex:p ex:o "question" "no" false)
          }
        }
        """,
        MultipleChoice,
    )
    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, MultipleChoice)
    assert presentation.choices == (Literal("yes"), Literal("no"))
    assert presentation.back == Literal("yes")


def test_entity_basic_contract(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?entity ?front ?back WHERE {
          VALUES (?entity ?front ?back) {(ex:country "question" "answer")}
        }
        """,
        target=TargetKind.ENTITY,
    )
    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, Basic)
    assert presentation.card_key == CardKey.entity(URIRef("https://example.org/country"))


def test_entity_deck_requires_entity_variable(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match=r"\?entity"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?front ?back WHERE {
              VALUES (?subject ?front ?back) {(ex:country "question" "answer")}
            }
            """,
            target=TargetKind.ENTITY,
        )


@pytest.mark.parametrize(
    "body",
    [
        'VALUES (?entity ?front ?back) {("entity" "f" "b")}',
        'VALUES (?front ?back) {("f" "b")} BIND(BNODE("entity") AS ?entity)',
    ],
)
def test_entity_contract_rejects_non_iris(tmp_path: Path, body: str) -> None:
    with pytest.raises(PresentationError, match="IRI"):
        run_query(
            tmp_path,
            f"SELECT ?entity ?front ?back WHERE {{ {body} }}",
            target=TargetKind.ENTITY,
        )


def test_entity_runtime_binding_selects_one_card(tmp_path: Path) -> None:
    query_path = tmp_path / "query.rq"
    query_path.write_text(
        PREFIX
        + """
        SELECT ?entity ?front ?back WHERE {
          ?entity ex:p ?back .
          BIND(STR(?entity) AS ?front)
        }
        """,
        encoding="utf-8",
    )
    deck = DeckDefinition(name="test", target=TargetKind.ENTITY, kind=Basic, query_path=query_path)
    graph = Graph().parse(
        data='@prefix ex: <https://example.org/> . ex:a ex:p "A" . ex:b ex:p "B" .',
        format="turtle",
    )
    key = CardKey.entity(URIRef("https://example.org/a"))
    presentations = execute_presentations(graph, deck, key)
    assert list(presentations) == [key.digest]


def test_runtime_binding_must_match_deck_target(tmp_path: Path) -> None:
    query_path = tmp_path / "query.rq"
    query_path.write_text(
        PREFIX + "SELECT ?entity ?front ?back WHERE { VALUES (?entity ?front ?back) {} }",
        encoding="utf-8",
    )
    deck = DeckDefinition(name="test", target=TargetKind.ENTITY, kind=Basic, query_path=query_path)
    triple = CardKey.triple(
        URIRef("https://example.org/s"),
        URIRef("https://example.org/p"),
        Literal("o"),
    )
    with pytest.raises(PresentationError, match="targets entity"):
        execute_presentations(Graph(), deck, triple)


def test_multiple_choice_rejects_invalid_typed_boolean_lexical_value(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="invalid xsd:boolean lexical value"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?predicate ?object ?front ?choice ?is_correct WHERE {
              VALUES (?subject ?predicate ?object ?front ?choice ?is_correct) {
                (ex:s ex:p ex:o "question" "yes" "TRUE"^^xsd:boolean)
                (ex:s ex:p ex:o "question" "no" false)
              }
            }
            """,
            MultipleChoice,
        )


@pytest.mark.parametrize(
    "query, kind, message",
    [
        (
            "SELECT ?subject ?predicate ?object ?front WHERE { "
            'VALUES (?subject ?predicate ?object ?front) {(ex:s ex:p ex:o "f")} }',
            Basic,
            "required variables",
        ),
        (
            "SELECT ?subject ?predicate ?object ?front ?back WHERE { "
            "VALUES (?subject ?predicate ?object ?front ?back) "
            '{(ex:s ex:p ex:o "f" "a") (ex:s ex:p ex:o "f" "b")} }',
            Basic,
            "conflicting",
        ),
        (
            "SELECT ?subject ?predicate ?object ?front ?choice ?is_correct WHERE { "
            "VALUES (?subject ?predicate ?object ?front ?choice ?is_correct) "
            '{(ex:s ex:p ex:o "q" "a" true)} }',
            MultipleChoice,
            "at least two",
        ),
        (
            "SELECT ?subject ?predicate ?object ?front ?choice ?is_correct WHERE { "
            "VALUES (?subject ?predicate ?object ?front ?choice ?is_correct) "
            '{(ex:s ex:p ex:o "q" "a" true) (ex:s ex:p ex:o "q" "b" true)} }',
            MultipleChoice,
            "exactly one",
        ),
        (
            "SELECT ?subject ?predicate ?object ?front ?choice ?is_correct WHERE { "
            "VALUES (?subject ?predicate ?object ?front ?choice ?is_correct) "
            '{(ex:s ex:p ex:o "q" "a" true) (ex:s ex:p ex:o "q" "a" false)} }',
            MultipleChoice,
            "same choice both correct and incorrect",
        ),
        (
            "SELECT ?subject ?predicate ?object ?front ?choice ?is_correct WHERE { "
            "VALUES (?subject ?predicate ?object ?front ?choice ?is_correct) "
            '{(ex:s ex:p ex:o "q" "a" "yes") (ex:s ex:p ex:o "q" "b" "no")} }',
            MultipleChoice,
            "xsd:boolean",
        ),
    ],
)
def test_invalid_result_contracts(
    tmp_path: Path, query: str, kind: type[DeckKind], message: str
) -> None:
    with pytest.raises(PresentationError, match=message):
        run_query(tmp_path, query, kind)


def test_non_select_query_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="SELECT"):
        run_query(tmp_path, "CONSTRUCT { ex:s ex:p ex:o } WHERE {}")


def test_unbound_required_value_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="unbound"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?predicate ?object ?front ?back WHERE {
              VALUES (?subject ?predicate ?object ?front ?back) {
                (ex:s ex:p ex:o "f" UNDEF)
              }
            }
            """,
        )
