---
# graphcards-ognd
title: Separate card data from presentation rendering
status: completed
type: feature
priority: normal
created_at: 2026-07-24T18:19:59Z
updated_at: 2026-07-25T01:14:03Z
---

Separate semantic card data from learner-facing rendering. This is independent of the composable-decks bean.

Design:
- Introduce a Card base model plus concrete data models such as BasicCard, MultipleChoiceCard, AnalogyCard, and OrderedListCard. Card subclasses contain only validated semantic/query data and the CardKey identity; they do not precompute learner-facing strings.
- Combine query generation and rendering in configured DeckDefinition subclasses. Each deck owns validated, overridable Jinja templates and renders its corresponding Card subclass into a CardView.
- Introduce CardView as the rendered result (replacing the proposed RenderedCard name), containing the learner-facing front and back strings and any other explicitly view-only values.
- Move card-data validation into Card models and enforce renderer/type compatibility at DeckDefinition.render().
- Perform randomized generation behavior, such as multiple-choice tier selection and choice ordering, before rendering when constructing the Card model; deck rendering does not receive an RNG or mutate card state.
- Make query execution produce Card models, and make study/web code use the configured deck to render them into CardView objects.
- Keep FSRS persistence and scheduling identity separate from both Card data and CardView; card data may be regenerated from queries.
- Update extension APIs, tests, documentation, and templates as needed.

Example flow:

SPARQL row -> card generation (including any RNG) -> Card subclass -> configured deck rendering with Jinja -> CardView

Built-in decks provide default inline templates; front_template and back_template may be overridden per deck in TOML, and render_context() exposes only curated card-derived values.

## Implementation Plan

- [x] Inventory current query, rendering, scheduling, study, web, and extension boundaries.
- [x] Add semantic Card models and CardView with domain validation and stable CardKey identity.
- [x] Combine type-safe Jinja rendering with configured DeckDefinition subclasses without RNG inputs.
- [x] Refactor query generation to create Cards, including all randomization, and render only at study/web boundaries.
- [x] Preserve FSRS scheduling persistence independently from semantic Cards and rendered CardViews.
- [x] Update extension APIs, templates, documentation, and behavior-focused tests.
- [x] Run focused tests and all repository quality gates.
- [x] Complete independent review/fix rounds until no actionable findings remain.
- [x] Append a summary, complete the bean, and commit only scoped files.

## Summary of Changes

- Added immutable semantic Card/CardView models and concrete BasicCard, MultipleChoiceCard, AnalogyCard, and OrderedListCard validation.
- Refactored deck queries to generate Cards, including multiple-choice random selection/order, and made configured DeckDefinition instances render CardViews through overridable inline Jinja templates.
- Moved rendering configuration and failure translation into DeckDefinition.render(); study/web consume CardViews while SQLite persists only CardKey identity and FSRS schedule state.
- Updated extension contracts, package dependencies/templates, documentation, and behavior-focused tests.
- Completed independent behavior, tests/edge-case, error/config/security, and API/docs review/fix rounds; all final reviews reported no actionable findings.
- Final verification: 259 tests passed; Ruff lint and format checks passed; uv.lock is current; sdist and wheel builds succeeded.

## Follow-up: Combine Decks and Rendering

- [x] Move validated configurable templates and rendering hooks into DeckDefinition.
- [x] Fold built-in Presentation implementations into their deck classes and remove the Presentation API.
- [x] Update configuration, extension docs, and behavior-focused tests for per-deck template overrides.
- [x] Run focused/full quality gates and independent review/fix rounds until clean.
- [x] Summarize the follow-up, complete the bean, and commit scoped files.

### Combined deck/rendering follow-up

Combined rendering into configured DeckDefinition instances, removed the Presentation hierarchy and option bridge, and made strict whitespace-preserving Jinja sources overridable per deck in TOML. Built-in decks retain their prior Card-to-CardView output, while analogy and ordered-list derived contexts now live on their deck classes and ordered-list rendering reads validated deck configuration directly. Exported TemplateSource for extensions, enforced its exact contract and defaults at registration, documented curated per-kind contexts, and preserved generation-only RNG plus separate FSRS persistence. Focused verification: 191 passed. Final verification: 259 tests passed; Ruff lint/format, uv lock, wheel/sdist build, and wheel-only API/render smoke tests passed. The initial reviews found trailing-newline and extension-contract gaps; both were fixed, and all four post-fix reviews reported no actionable findings.
