from __future__ import annotations

from pathlib import Path

from graphcards.config import load_config
from tests.web.support import exchange, make_test_hub, start_session


def test_web_study_renders_analogy_front_then_labelled_answer(tmp_path: Path) -> None:
    query_path = tmp_path / "analogy.rq"
    query_path.write_text(
        """
        PREFIX ex: <https://example.org/>
        SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
               ?subject_label ?predicate_label ?object_label
               ?source_subject_label ?source_predicate_label ?source_object_label
        WHERE {
          VALUES (?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide
                  ?subject_label ?predicate_label ?object_label
                  ?source_subject_label ?source_predicate_label ?source_object_label) {
            (ex:France ex:capital ex:Paris ex:Germany ex:capital ex:Berlin "object"
             "France" "capital of" "Paris" "Germany" "capital of" "Berlin")
          }
        }
        """,
        encoding="utf-8",
    )
    config_path = tmp_path / "graphcards.toml"
    config_path.write_text(
        'state_path = "state.sqlite3"\n'
        '[[decks]]\nname = "analogy"\ntarget = "triple"\nkind = "analogy"\n'
        'query = "analogy.rq"\n',
        encoding="utf-8",
    )
    server = make_test_hub(load_config(config_path))
    try:
        session = start_session(server, "analogy")
        assert session.current is not None

        status, _, body = exchange(server, "GET", "/study")
        assert status == 200
        assert "Germany capital of Berlin :: France capital of ?" in body
        assert "Paris" not in body

        fields = {
            "session_token": session.session_token,
            "card_id": session.current.card.card_id,
        }
        assert exchange(server, "POST", "/study/reveal", fields)[0] == 303
        status, _, body = exchange(server, "GET", "/study")
        assert status == 200
        assert "Answer" in body
        assert "Paris" in body
    finally:
        server.close()
