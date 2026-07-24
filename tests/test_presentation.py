from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from rdfcards.config import DeckDefinition
from rdfcards.decks import Basic, DeckKind, MultipleChoice, OrderedListCompletion
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
    max_choices: int | None = None,
    window_size: int | None = None,
) -> dict[str, object]:
    query_path = tmp_path / "query.rq"
    query_path.write_text(PREFIX + query, encoding="utf-8")
    deck = DeckDefinition(
        name="test",
        target=target,
        kind=kind,
        query_path=query_path,
        max_choices=max_choices,
        window_size=window_size,
    )
    return execute_presentations(Graph(), deck)


def run_ordered_query(
    tmp_path: Path,
    rows: str,
    *,
    window_size: int | None = None,
) -> dict[str, object]:
    return run_query(
        tmp_path,
        f"""
        SELECT ?entity ?group ?position ?label WHERE {{
          VALUES (?entity ?group ?position ?label) {{
            {rows}
          }}
        }}
        """,
        OrderedListCompletion,
        target=TargetKind.ENTITY,
        window_size=window_size,
    )


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
    assert tuple(option.choice for option in presentation.choices) == (
        Literal("yes"),
        Literal("no"),
    )
    assert tuple(option.priority for option in presentation.choices) == (0, 0)
    assert presentation.max_choices == 4
    assert presentation.back == Literal("yes")


def test_multiple_choice_normalizes_optional_priorities(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?front ?choice ?is_correct ?priority WHERE {
          VALUES (?subject ?predicate ?object ?front ?choice ?is_correct ?priority) {
            (ex:s ex:p ex:o "question" "correct" true 0)
            (ex:s ex:p ex:o "question" "high" false 3)
            (ex:s ex:p ex:o "question" "default" false UNDEF)
          }
        }
        """,
        MultipleChoice,
        max_choices=2,
    )

    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, MultipleChoice)
    assert tuple((option.choice, option.priority) for option in presentation.choices) == (
        (Literal("correct"), 0),
        (Literal("high"), 3),
        (Literal("default"), 0),
    )
    assert presentation.max_choices == 2


def test_multiple_choice_accepts_duplicate_missing_and_zero_priority(tmp_path: Path) -> None:
    presentations = run_query(
        tmp_path,
        """
        SELECT ?subject ?predicate ?object ?front ?choice ?is_correct ?priority WHERE {
          VALUES (?subject ?predicate ?object ?front ?choice ?is_correct ?priority) {
            (ex:s ex:p ex:o "question" "correct" true UNDEF)
            (ex:s ex:p ex:o "question" "incorrect" false UNDEF)
            (ex:s ex:p ex:o "question" "incorrect" false 0)
          }
        }
        """,
        MultipleChoice,
    )

    presentation = next(iter(presentations.values()))
    assert isinstance(presentation, MultipleChoice)
    assert len(presentation.choices) == 2


@pytest.mark.parametrize(
    ("priority", "message"),
    [
        ('"1"', "xsd:integer literal"),
        ("1.5", "xsd:integer literal"),
        ("true", "xsd:integer literal"),
        ("-1", "zero or greater"),
        ('"not-an-integer"^^xsd:integer', "invalid xsd:integer"),
    ],
)
def test_multiple_choice_rejects_invalid_priority(
    tmp_path: Path,
    priority: str,
    message: str,
) -> None:
    with pytest.raises(PresentationError, match=message):
        run_query(
            tmp_path,
            f"""
            SELECT ?subject ?predicate ?object ?front ?choice ?is_correct ?priority WHERE {{
              VALUES (?subject ?predicate ?object ?front ?choice ?is_correct ?priority) {{
                (ex:s ex:p ex:o "question" "correct" true 0)
                (ex:s ex:p ex:o "question" "incorrect" false {priority})
              }}
            }}
            """,
            MultipleChoice,
        )


def test_multiple_choice_rejects_conflicting_duplicate_priorities(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="conflicting priorities"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?predicate ?object ?front ?choice ?is_correct ?priority WHERE {
              VALUES (?subject ?predicate ?object ?front ?choice ?is_correct ?priority) {
                (ex:s ex:p ex:o "question" "correct" true 0)
                (ex:s ex:p ex:o "question" "incorrect" false 1)
                (ex:s ex:p ex:o "question" "incorrect" false 2)
              }
            }
            """,
            MultipleChoice,
        )


def test_multiple_choice_validates_lower_tiers_that_will_not_be_displayed(
    tmp_path: Path,
) -> None:
    with pytest.raises(PresentationError, match="xsd:integer literal"):
        run_query(
            tmp_path,
            """
            SELECT ?subject ?predicate ?object ?front ?choice ?is_correct ?priority WHERE {
              VALUES (?subject ?predicate ?object ?front ?choice ?is_correct ?priority) {
                (ex:s ex:p ex:o "question" "correct" true 0)
                (ex:s ex:p ex:o "question" "high" false 2)
                (ex:s ex:p ex:o "question" "unused low" false "invalid")
              }
            }
            """,
            MultipleChoice,
            max_choices=2,
        )


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


def test_ordered_list_hides_target_and_keeps_entity_identity(tmp_path: Path) -> None:
    presentations = run_ordered_query(
        tmp_path,
        '(ex:a ex:group 1 "Alpha")\n(ex:b ex:group 2 "Beta")\n(ex:c ex:group 3 "Gamma")',
    )

    target = presentations[CardKey.entity(URIRef("https://example.org/b")).digest]
    assert isinstance(target, OrderedListCompletion)
    assert target.card_key == CardKey.entity(URIRef("https://example.org/b"))
    assert str(target.front) == "1. Alpha\n2. ?\n3. Gamma"
    assert target.back == Literal("Beta")


def test_ordered_list_centers_window_and_shows_omitted_boundaries(tmp_path: Path) -> None:
    presentations = run_ordered_query(
        tmp_path,
        "\n".join(f'(ex:e{n} ex:group {n} "E{n}")' for n in range(1, 8)),
    )

    target = presentations[CardKey.entity(URIRef("https://example.org/e4")).digest]
    assert str(target.front) == "…\n2. E2\n3. E3\n4. ?\n5. E5\n6. E6\n…"


@pytest.mark.parametrize(
    ("entity", "expected"),
    [
        ("e1", "1. ?\n2. E2\n3. E3\n4. E4\n5. E5\n…"),
        ("e7", "…\n3. E3\n4. E4\n5. E5\n6. E6\n7. ?"),
    ],
)
def test_ordered_list_shifts_window_at_boundaries(
    tmp_path: Path,
    entity: str,
    expected: str,
) -> None:
    presentations = run_ordered_query(
        tmp_path,
        "\n".join(f'(ex:e{n} ex:group {n} "E{n}")' for n in range(1, 8)),
    )

    target = presentations[CardKey.entity(URIRef(f"https://example.org/{entity}")).digest]
    assert str(target.front) == expected


def test_ordered_list_zero_window_size_shows_full_list(tmp_path: Path) -> None:
    presentations = run_ordered_query(
        tmp_path,
        "\n".join(f'(ex:e{n} ex:group {n} "E{n}")' for n in range(1, 8)),
        window_size=0,
    )

    target = presentations[CardKey.entity(URIRef("https://example.org/e4")).digest]
    assert str(target.front) == "\n".join(
        ["1. E1", "2. E2", "3. E3", "4. ?", "5. E5", "6. E6", "7. E7"]
    )
    assert "…" not in str(target.front)


def test_ordered_list_study_render_executes_full_query_before_selecting_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_path = tmp_path / "query.rq"
    query_path.write_text(
        PREFIX
        + """
        SELECT ?entity ?group ?position ?label WHERE {
          VALUES (?entity ?group ?position ?label) {
            (ex:a ex:group 1 "Alpha")
            (ex:b ex:group 2 "Beta")
          }
        }
        """,
        encoding="utf-8",
    )
    deck = DeckDefinition(
        name="ordered",
        target=TargetKind.ENTITY,
        kind=OrderedListCompletion,
        query_path=query_path,
    )
    graph = Graph()
    original_query = graph.query
    init_bindings: list[object] = []

    def recording_query(*args: object, **kwargs: object):
        init_bindings.append(kwargs.get("initBindings"))
        return original_query(*args, **kwargs)

    monkeypatch.setattr(graph, "query", recording_query)
    execute_presentations(
        graph,
        deck,
        CardKey.entity(URIRef("https://example.org/b")),
    )

    assert init_bindings == [None]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ('(ex:a ex:g 1 "A")', "at least two"),
        ('(ex:a ex:g 1 "A")\n(ex:b ex:g 3 "B")', "contiguous"),
        ('(ex:a ex:g 1 "A")\n(ex:b ex:g 1 "B")', "unique"),
        ('(ex:a ex:g 1 "A")\n(ex:a ex:h 2 "A")', "multiple"),
        ('(ex:a ex:g 0 "A")\n(ex:b ex:g 1 "B")', "at least 1"),
        ('(ex:a ex:g "1" "A")\n(ex:b ex:g 2 "B")', "xsd:integer"),
        ('("not-an-iri" ex:g 1 "A")\n(ex:b ex:g 2 "B")', "IRI"),
    ],
)
def test_ordered_list_rejects_invalid_group_rows(
    tmp_path: Path,
    rows: str,
    message: str,
) -> None:
    with pytest.raises(PresentationError, match=message):
        run_ordered_query(tmp_path, rows)


def test_ordered_list_requires_exact_query_projection(tmp_path: Path) -> None:
    with pytest.raises(PresentationError, match="exactly"):
        run_query(
            tmp_path,
            """
            SELECT ?entity ?group ?position ?label ?extra WHERE {
              VALUES (?entity ?group ?position ?label ?extra) {
                (ex:a ex:g 1 "A" "extra")
                (ex:b ex:g 2 "B" "extra")
              }
            }
            """,
            OrderedListCompletion,
            target=TargetKind.ENTITY,
        )


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
