---
# graphcards-rlsk
title: Composable decks from inline card sources
status: todo
type: feature
priority: normal
created_at: 2026-07-24T05:23:00Z
updated_at: 2026-07-24T18:05:29Z
---

Replace the current single-query deck abstraction with true composed decks. The existing query/presentation definition becomes a card source; each user-facing deck is configured with one or more inline sources. This is a breaking terminology and configuration change.

Proposed configuration:

[[decks]]
name = "capital-review"

[[decks.sources]]
kind = "basic"
target = "triple"
query = "queries/capitals-basic.rq"

[[decks.sources]]
kind = "analogy"
target = "triple"
query = "queries/capitals-analogy.rq"

Requirements:
- Rename the current DeckDefinition concept to a card/presentation source definition and introduce a true Deck aggregate.
- Keep source definitions inline and non-reusable; source entries need no user-facing names.
- Allow one deck to mix entity and triple sources and any registered presentation kinds.
- Synchronize the union of all source presentations into one deck membership queue.
- Preserve one global FSRS schedule per card identity and one membership per composed deck.
- Treat duplicate card identities produced by multiple sources in the same deck as a validation/presentation error.
- Resolve a scheduled card back to exactly one source presentation for rendering.
- Keep deck-oriented web study, status, history, suspension, and review behavior.
- Update extension APIs, CLI/config validation, docs, templates, and behavioral tests for the breaking rename.

Out of scope unless separately specified: selecting RDF files per card source, reusable named sources, source weighting/order policies, or compatibility with the old single-source deck configuration.



Configuration association:

Each `[[decks.sources]]` entry is nested under the immediately preceding `[[decks]]` table. For example:

```toml
[[decks]]
name = "capital-review"

[[decks.sources]]
kind = "basic"
target = "triple"
query = "queries/capitals-basic.rq"

[[decks.sources]]
kind = "analogy"
target = "triple"
query = "queries/capitals-analogy.rq"

[[decks]]
name = "planet-review"

[[decks.sources]]
kind = "ordered_list"
target = "entity"
query = "queries/planets.rq"
```

The parsed model should associate the first two sources with `capital-review` and the last source with `planet-review`.
