# RDFCards

RDFCards is a local flashcard program in which the thing being learned is either an RDF triple
or an IRI-identified RDF entity. SPARQL queries define how each card is presented. The same
triple or entity has one FSRS schedule even when several decks present it differently.

## Install and try it

RDFCards requires Python 3.14. This repository uses
[uv](https://docs.astral.sh/uv/):

```console
uv sync
uv run rdfcards init demo
uv run rdfcards templates
uv run rdfcards init capitals-demo --template capitals
```

`init` requires a destination and creates an empty `rdfcards.toml` with no sources or decks.
It refuses to overwrite an existing configuration. Add your RDF sources, presentation queries,
and deck definitions before validating or studying the workspace. The optional `--template NAME`
flag creates a bundled workspace template instead. Run `rdfcards templates` to list the names
available in the installed package; `capitals` provides working triple-backed
basic cards and entity-backed multiple-choice cards.

## Configuration

Paths are relative to the TOML file, not to the process's working directory.
Empty `sources` and `decks` arrays are valid.

```toml
state_path = ".rdfcards/state.sqlite3"
sources = ["data/knowledge.ttl"]

[fsrs]
desired_retention = 0.9
maximum_interval = 36500
learning_steps_minutes = [1, 10]
relearning_steps_minutes = [10]
enable_fuzzing = true

[[decks]]
name = "capitals-basic"
target = "triple"
kind = "basic"
query = "queries/capitals-basic.rq"
```

All configured RDF sources are loaded into one RDFLib graph. RDFLib determines the format from
the filename. The state database is separate from the RDF files and may safely be excluded from
version control. Pydantic validates configuration and the immutable card and presentation models.

## Presentation query contract

Every deck uses a SPARQL `SELECT` query and declares one identity `target`.

A `target = "triple"` deck must bind:

- `?subject`
- `?predicate`
- `?object`

Every deck must declare `target`. Triple subjects and predicates must be IRIs; objects may be
IRIs or literals. No triple term may be a blank node.

A `target = "entity"` deck instead binds `?entity`, which must be an IRI. Literals and blank
nodes cannot identify entity cards.

Presentation variables are independent of the target. A `kind = "basic"` deck binds `?front`
and `?back`. One card may occur in duplicate identical rows, but conflicting front/back pairs
are rejected.

Internally, each configured kind resolves to a `DeckKind` subclass. That class declares its
required variables, groups SPARQL rows into front/back presentations, and formats its front.
The CLI applies one reveal-and-rate interaction to every presentation without branching on kind
names.

```sparql
SELECT ?subject ?predicate ?object ?front ?back
WHERE {
  ?subject <https://example.org/capital> ?object .
  BIND(CONCAT("Capital of ", STR(?subject), "?") AS ?front)
  BIND(STR(?object) AS ?back)
  BIND(<https://example.org/capital> AS ?predicate)
}
```

A `kind = "multiple_choice"` deck binds `?front`, `?choice`, and `?is_correct`. Each choice is
one row and `?is_correct` must be an `xsd:boolean`. Each card must have one front, at least two
distinct choices, and exactly one correct choice. This entity-backed query is representative:

```sparql
SELECT ?entity ?front ?choice ?is_correct
WHERE {
  ?entity <https://example.org/capital> ?correctAnswer .
  ?candidate a <https://example.org/City> .
  BIND(STR(?entity) AS ?front)
  BIND(STR(?candidate) AS ?choice)
  BIND(?candidate = ?correctAnswer AS ?is_correct)
}
```

The query is run once to synchronize deck membership. Immediately before a due card is shown,
it is run again with either `?subject`/`?predicate`/`?object` or `?entity` pre-bound to the
scheduled identity. Queries should use those variables directly rather than overwriting them.

## Card identity and graph changes

Card IDs are SHA-256 hashes with separate domain markers for triples and entities. Triple hashes
contain the length-prefixed N3 forms of subject, predicate, and object; entity hashes contain the
length-prefixed N3 form of the entity IRI. An entity and a triple mentioning it are therefore
distinct cards. Length prefixes prevent concatenation ambiguity, and N3 retains literal datatypes
and language tags.

Synchronization never resets a known card. If an identity disappears from a deck query, its deck
association becomes inactive but its schedule and reviews remain. If it reappears, that schedule
is restored. Changing a triple term or entity IRI creates a new card. Matching triples share a
schedule across triple decks, and matching entities share one across entity decks; triple and
entity schedules never merge.

RDFCards uses schema v3 state and does not migrate other schema versions. If it reports an
unsupported version, move or delete the database and run `sync` to create fresh state.

## How synchronization works

```console
rdfcards --config rdfcards.toml sync
rdfcards --config rdfcards.toml sync --deck capitals-basic
```

`sync` loads all configured RDF sources into one graph and executes the presentation query for
each selected deck. Every result is validated and converted into a triple- or entity-backed card
identity before SQLite is changed.

Each deck is reconciled in one transaction:

1. Existing memberships for that deck are marked inactive.
2. Cards returned by the current query are inserted or reactivated.
3. New identities receive a new FSRS card due immediately.
4. Existing identities retain their schedule and review history.
5. Identities no longer returned remain inactive without losing their history.

Cards are global while deck memberships are local. The same triple shared by two triple decks,
or the same entity shared by two entity decks, therefore has one FSRS schedule. Triple and entity
cards remain separate even when they refer to the same IRI. Any query, identity, or database
failure rolls back the selected deck's reconciliation.

## SQLite schema

The state file uses SQLite schema version 3. `cards` owns the global FSRS schedule, `deck_cards`
tracks per-deck membership, and `reviews` stores the immutable review history.

```sql
CREATE TABLE cards (
    card_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('triple', 'entity')),
    identity_json TEXT NOT NULL,
    card_json TEXT NOT NULL,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX cards_due_at_idx ON cards(due_at);

CREATE TABLE deck_cards (
    deck_name TEXT NOT NULL,
    card_id TEXT NOT NULL REFERENCES cards(card_id),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (deck_name, card_id)
);
CREATE INDEX deck_cards_active_idx ON deck_cards(deck_name, active);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(card_id),
    deck_name TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    reviewed_at TEXT NOT NULL,
    review_json TEXT NOT NULL
);
CREATE INDEX reviews_card_idx ON reviews(card_id, reviewed_at);

PRAGMA user_version = 3;
```

`identity_json` is a JSON array of canonical RDF N3 terms. It contains one IRI for entity cards
or the subject, predicate, and object for triple cards. `card_json` and `review_json` are the
serialized py-fsrs objects. All timestamp columns contain UTC ISO 8601 text.

## Commands

```text
rdfcards [-c PATH] init DIRECTORY [--template NAME]
rdfcards [-c PATH] templates
rdfcards [-c PATH] validate [--deck NAME]
rdfcards [-c PATH] sync [--deck NAME]
rdfcards [-c PATH] status [--deck NAME] [--full]
rdfcards [-c PATH] study NAME [--limit N]
```

`validate` does not create or modify study state. `status --full` follows each deck summary with
a card-level table containing the identity hash, target, due status, FSRS state, review count,
UTC due time, and RDF identity. `study` synchronizes its selected deck before selecting due cards.
A limit of zero means no session limit. Both basic and multiple-choice cards show the front,
wait for Enter, reveal the back, and ask for one of the four FSRS ratings. Multiple-choice fronts
include shuffled choices, and their back is the correct choice.

All scheduling timestamps are UTC. Changing FSRS configuration affects future reviews; existing
cards are not automatically rescheduled.

## Development

```console
uv run pytest
uv run ruff check .
uv build
```

The application is intentionally local and single-user. Remote SPARQL endpoints, web interfaces,
media rendering, synchronization, blank-node canonicalization, and FSRS parameter optimization
are outside v1.
