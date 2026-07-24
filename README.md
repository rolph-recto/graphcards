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
uv run rdfcards init priority-demo --template priority-capitals
```

`init` requires a destination and creates an empty `rdfcards.toml` with no sources or decks.
It refuses to overwrite an existing configuration. Add your RDF sources, presentation queries,
and deck definitions before validating or studying the workspace. The optional `--template NAME`
flag creates a bundled workspace template instead. Run `rdfcards templates` to list the names
available in the installed package; `capitals` provides working triple-backed
basic cards and entity-backed multiple-choice cards. `priority-capitals` is a
focused multiple-choice example with five candidates, four displayed choices,
several priority tiers, and a cutoff tie.

## Configuration

Paths are relative to the TOML file, not to the process's working directory.
Empty `sources` and `decks` arrays are valid.

```toml
state_path = ".rdfcards/state.sqlite3"
display_timezone = "America/New_York"
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

[[decks]]
name = "capitals-choice"
target = "entity"
kind = "multiple_choice"
query = "queries/capitals-choice.rq"
max_choices = 4
```

All configured RDF sources are loaded into one RDFLib graph. RDFLib determines the format from
the filename. The state database is separate from the RDF files and may safely be excluded from
version control. `display_timezone` accepts an IANA timezone name and defaults to `UTC`; it controls
browser date labels, history buckets, and streak-day boundaries without changing UTC storage.
Pydantic validates configuration and the immutable card and presentation models.

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
distinct choices, and exactly one correct choice.

The query may also bind `?priority` for each choice. A bound priority must be an `xsd:integer`
literal with a value of zero or greater; malformed lexical values, other RDF datatypes, and
negative values are rejected. An omitted or unbound priority defaults to zero. Larger numbers
have higher priority. Duplicate rows for the same choice must agree on both correctness and the
effective priority.

Multiple-choice decks accept `max_choices`, a strict integer of at least two that defaults to
four. It counts the correct answer as well as distractors. RDFCards validates the complete query
result, always includes the correct answer, and then fills the remaining slots by exhausting
higher-priority distractor tiers before considering lower-priority tiers. Ties within a tier are
randomized before RDFCards fills the available slots. It then separately shuffles the full
retained set, including the correct answer, for display. Repeated presentations draw from the
study session's continuing random-number stream, so a cutoff tie and the displayed order can
vary from one render to the next. If the query returns fewer choices than the configured maximum,
all choices are shown.

A `kind = "ordered_list"` deck tests an entity's place in a labeled, non-cyclic ordered list. Its
query must select exactly `?entity`, `?group`, `?position`, and `?label`. Each group must contain at
least two rows with unique, contiguous positions starting at one, and each entity may occur in
only one group. The complete query runs when a card is rendered; the scheduled entity's row is
shown as `?`, while its IRI remains the card identity and its label is shown after reveal. The
optional `window_size` deck setting defaults to five; `window_size = 0` shows the complete list.
Longer lists use a contiguous window around the tested position and show `…` for omitted items at
the beginning or end.

This entity-backed query is representative:

```sparql
PREFIX ex: <https://example.org/>

SELECT ?entity ?front ?choice ?is_correct ?priority
WHERE {
  ?entity ex:capital ?correctAnswer .

  {
    {
      SELECT ?entity ?candidate (0 AS ?priority)
      WHERE { ?entity ex:capital ?candidate }
    }
    UNION
    {
      SELECT ?entity ?candidate (3 AS ?priority)
      WHERE {
        VALUES (?entity ?candidate) {
          (ex:France ex:Berlin)
          (ex:Germany ex:Paris)
        }
      }
    }
  }

  ?candidate a ex:City .
  BIND(STR(?entity) AS ?front)
  BIND(STR(?candidate) AS ?choice)
  BIND(?candidate = ?correctAnswer AS ?is_correct)
}
```

Additional `UNION` branches can supply lower-priority choice groups. The bundled
`priority-capitals` template contains a complete example with four subqueries and a randomized
cutoff tie.

Invalid `max_choices` values are configuration errors. Invalid priority bindings and conflicting
choice rows are presentation errors, so `validate`, `sync`, terminal study, and browser study all
report the same query contract.

The query is run once to synchronize deck membership. Immediately before a due card is shown,
ordinary decks run it again with either `?subject`/`?predicate`/`?object` or `?entity` pre-bound to
the scheduled identity. Ordered-list decks intentionally run their full query unbound, validate
all groups, and select the scheduled entity in application code. Queries should use identity
variables directly rather than overwriting them.

## Card identity and graph changes

Card IDs are SHA-256 hashes with separate domain markers for triples and entities. Triple hashes
contain the length-prefixed N3 forms of subject, predicate, and object; entity hashes contain the
length-prefixed N3 form of the entity IRI. An entity and a triple mentioning it are therefore
distinct cards. Length prefixes prevent concatenation ambiguity, and N3 retains literal datatypes
and language tags.

Synchronization never resets a known card. If an identity disappears from a deck query, its deck
association becomes inactive but its schedule, suspension, and reviews remain. If it reappears,
that state is restored. Changing a triple term or entity IRI creates a new card. Matching triples
share a schedule across triple decks, and matching entities share one across entity decks; triple
and entity schedules never merge.

RDFCards uses schema v4 state and migrates schema v3 databases in place. The additive migration
does not rewrite cards or reviews; existing memberships start unsuspended. Other schema versions
remain unsupported. A schema v4 database cannot be opened by an older RDFCards version, so make a
copy of important state before upgrading.

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
2. Cards returned by the current query are inserted or reactivated without overwriting suspension.
3. New identities receive a new FSRS card due immediately.
4. Existing identities retain their schedule and review history.
5. Identities no longer returned remain inactive without losing their history or suspension.

Cards are global while deck memberships are local. The same triple shared by two triple decks,
or the same entity shared by two entity decks, therefore has one FSRS schedule. Triple and entity
cards remain separate even when they refer to the same IRI. Any query, identity, or database
failure rolls back the selected deck's reconciliation.

Suspension is local to a deck membership. Suspending a shared card in one deck does not suspend it
in another. Reviews through another deck can still advance the shared global schedule, and the
resumed membership uses that current schedule. Renaming a deck creates different memberships and
does not transfer suspension from the old deck name.

## SQLite schema

The state file uses SQLite schema version 4. `cards` owns the global FSRS schedule, `deck_cards`
tracks per-deck membership and current suspension, and `reviews` stores immutable rating history.

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
    suspended INTEGER NOT NULL DEFAULT 0 CHECK (suspended IN (0, 1)),
    suspension_reason TEXT CHECK (
        suspension_reason IS NULL OR (
            length(suspension_reason) BETWEEN 1 AND 500
            AND suspension_reason = trim(suspension_reason)
        )
    ),
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (deck_name, card_id)
);
CREATE INDEX deck_cards_active_idx ON deck_cards(deck_name, active);
CREATE INDEX deck_cards_queue_idx
    ON deck_cards(deck_name, active, suspended, card_id);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(card_id),
    deck_name TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    reviewed_at TEXT NOT NULL,
    review_json TEXT NOT NULL
);
CREATE INDEX reviews_card_idx ON reviews(card_id, reviewed_at);
CREATE INDEX reviews_deck_time_idx ON reviews(deck_name, reviewed_at, id);

PRAGMA user_version = 4;
```

`identity_json` is a JSON array of canonical RDF N3 terms. It contains one IRI for entity cards
or the subject, predicate, and object for triple cards. `card_json` is the serialized py-fsrs
card. `review_json` contains the py-fsrs review log plus optional immutable interval and
pre-review retrievability values used by browser analytics. Records created before those values
were available still contribute to volume, ratings, and streaks. All timestamp columns contain
UTC ISO 8601 text. Suspension and its optional reason are current membership state, not review
events; resuming clears the reason and does not add or alter review history.

## Commands

```text
rdfcards [-c PATH] init DIRECTORY [--template NAME]
rdfcards [-c PATH] templates
rdfcards [-c PATH] validate [--deck NAME]
rdfcards [-c PATH] sync [--deck NAME]
rdfcards [-c PATH] status [--deck NAME] [--full]
rdfcards [-c PATH] study NAME [--limit N]
rdfcards [-c PATH] suspend DECK CARD_ID [--reason TEXT]
rdfcards [-c PATH] resume DECK CARD_ID
rdfcards [-c PATH] serve
```

`validate` does not create or modify study state. `status --full` follows each deck summary with
a card-level table containing the identity hash, target, due status, FSRS state, review count,
UTC due time, suspension reason, and RDF identity. Use the full card ID with `suspend` or `resume`;
these commands use persisted membership state without loading RDF sources. Reasons are optional,
trimmed, single-line text limited to 500 characters; control characters, Unicode format controls,
and line separators are rejected. Reasons are cleared on resume. An inactive membership can be
resumed from the CLI before its card reappears in a later sync.

`study` synchronizes its selected deck before selecting due cards. Suspended cards are excluded
from due study, practice, forgotten review, and review-ahead queues without changing their FSRS
schedule. A resumed card returns at its existing schedule and may therefore be immediately due.
A limit of zero means no session limit. Basic, multiple-choice, and ordered-list cards show the
front, wait for Enter, reveal the back, and ask for one of the four FSRS ratings. Multiple-choice
fronts include their priority-selected shuffled choices, ordered-list fronts include the bounded
list window, and each back shows its configured answer.

Run `serve` to open the Flask-based browser study interface. RDFCards synchronizes every
configured deck, binds its single-threaded local server to an automatically selected port on
`127.0.0.1`, prints and opens the local URL, and keeps serving until Ctrl-C. The deck list shows
current available and suspended counts and supports regular due-card study, reviewing recently
forgotten cards, schedule-free deck practice, and reviewing future cards ahead of time. Each deck
also links to a page that shows review history first, followed by current card status using N3 RDF
identities, next review, FSRS state, stability, difficulty, and current retrievability. Status can
be filtered by availability, schedule, or FSRS state, sorted by scheduling metrics, and show 100
cards per page. Suspended rows show the optional reason and a Resume action. Available rows can be
suspended with an optional reason, and the current study card can be suspended without recording a
review. The same page
includes immutable review analytics for selectable 30-day, 90-day, one-year, and all-time ranges:
review volume, rating distribution and Again rate, active-day streaks, interval growth, and
pre-review FSRS retrievability where recorded. History follows the deck used for each review and
continues to include cards that are no longer active in that deck. Browser sessions use stable
card snapshots, preserve the current card across refreshes, and save a scheduled review only after
a valid rating is submitted. Suspension takes effect immediately: pending suspended cards are
skipped, and a stale form cannot review a card after it is suspended.

All scheduling timestamps are stored in UTC. The browser formats them in `display_timezone`.
Changing FSRS configuration affects future reviews; existing cards are not automatically
rescheduled.

## Development

```console
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

The application is intentionally local and single-user. Remote SPARQL endpoints, remotely hosted
web interfaces, media rendering, synchronization, blank-node canonicalization, and FSRS parameter
optimization are outside v1.
