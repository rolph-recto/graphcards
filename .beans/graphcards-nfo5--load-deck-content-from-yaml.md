---
# graphcards-nfo5
title: Load deck content from YAML
status: todo
type: feature
priority: normal
created_at: 2026-07-28T04:19:50Z
updated_at: 2026-07-28T04:19:50Z
blocked_by:
    - graphcards-npyi
---

Allow configured deck content to be authored as YAML in addition to JSON and TOML. This feature extends the suffix-selected deck parser introduced by `graphcards-npyi`; the workspace configuration itself remains TOML.

## Problem

Deck content is format-independent after parsing, but `Deck.load` does not accept `.yaml` or `.yml` files. Users who prefer YAML cannot author decks in that format or mix YAML decks with the other supported formats in one workspace.

## Proposed behavior

- Select YAML parsing for case-insensitive `.yaml` and `.yml` suffixes while preserving the existing JSON and TOML branches.
- Use a maintained YAML dependency in safe-loading mode; update `pyproject.toml` and `uv.lock`.
- Require a single YAML document whose root has the same `name`, `entities`, and `exercises` shape validated by `DeckDocument`.
- Express repeated entities and exercises as YAML sequences and generator maps such as `choices`, `groups`, `sources`, and `relations` as YAML mappings.
- Reject duplicate mapping keys at every nesting level instead of silently keeping one value.
- Do not permit arbitrary Python object construction or unsafe custom tags.
- Preserve stable parent-directory deck identity, rendering preflight, card identity, JSON/TOML behavior, and mixed-format workspaces.
- Translate YAML scanner/parser/composer/constructor failures, file I/O, Unicode, unsupported scalar types, and Pydantic failures into the existing user-facing `ConfigError`.

## Acceptance criteria

- [ ] `Deck.load` successfully loads valid `.yaml` and `.yml` decks containing entities and every supported generator type.
- [ ] `load_config` accepts relative YAML deck paths and can load JSON, TOML, and YAML decks side by side.
- [ ] A YAML deck produces the same validated document, deterministic generated card identities and payloads, and rendered views as equivalent JSON and TOML decks.
- [ ] The YAML loader is safe, rejects duplicate keys, rejects unsupported custom tags, and does not allow YAML-native scalar types or cyclic structures to escape the deck’s JSON-compatible domain.
- [ ] Malformed YAML, multiple documents, empty documents, non-mapping roots, unsupported extensions, missing/non-file paths, unknown generators, invalid references, and invalid nested generator data surface as path-qualified `ConfigError`.
- [ ] Existing JSON and TOML loading remains covered and unchanged.
- [ ] CLI validation and sync work with YAML-backed decks, and bundled documentation includes a minimal YAML deck example.
- [ ] Focused parser, parity, config, CLI, safety, and error-translation tests pass together with all required repository checks.

## Non-goals

- Converting or rewriting existing deck files.
- Round-trip YAML editing or preservation of comments, anchors, formatting, or key order beyond the semantic order already used by the deck schema.
- Adding YAML-only domain fields or changing `DeckDocument`.
- Replacing `graphcards.toml` as the workspace configuration format.
- Supporting arbitrary YAML tags or Python-specific YAML objects.

## Recommended design decisions

- Build on the format-decoding helper from `graphcards-npyi` rather than adding format branches back into domain validation.
- Support both `.yaml` and `.yml`, case-insensitively, without content sniffing.
- Use `PyYAML` `SafeLoader` (or an equivalently maintained safe parser selected during implementation) with a small custom mapping constructor that rejects duplicate keys recursively. Do not use `FullLoader`, `UnsafeLoader`, or generic object construction.
- Decide and document an explicit anchor/alias policy. At minimum, reject cyclic alias graphs and ensure aliases cannot bypass duplicate-key checks, JSON-compatible value validation, or practical parser resource limits. Reject YAML merge keys if correct duplicate detection and bounded expansion cannot be guaranteed.
- Treat YAML’s implicit timestamps, sets, binary values, and other non-JSON-native results as invalid deck data. Booleans, strings, finite numbers, nulls, sequences, and string-keyed mappings remain valid when the domain schema accepts them.
- Keep one Pydantic v2 `DeckDocument.model_validate` boundary for JSON, TOML, and YAML.
- Preserve useful YAML line/column diagnostics in the `ConfigError` message while consistently including the deck path.

## Implementation plan

1. **Add a safe YAML parser at the existing decoder boundary.**
   - Add the selected YAML dependency to `pyproject.toml` with an appropriate compatible range and refresh `uv.lock`.
   - Extend the format-dispatch helper in `src/graphcards/decks/base.py` for `.yaml` and `.yml`.
   - Implement safe, duplicate-key-aware loading of exactly one document and normalize all parser/library failures through the current deck error boundary.
   - Recursively validate parser output as acyclic, finite, string-keyed, and JSON-compatible before or as part of `DeckDocument` validation so YAML-native objects cannot enter entity metadata.

2. **Add complete YAML loader and parity tests.**
   - Add a canonical hand-authored YAML deck covering basic, multiple-choice, ordered-list, analogy, and common-relation generators, nested entity metadata, and custom templates.
   - Load equivalent JSON, TOML, and YAML files from the same parent directory and compare model dumps, seeded generated exercises and card keys, and rendered views.
   - Parameterize `.yaml`, `.yml`, and mixed-case suffix behavior.

3. **Test parser safety and user-facing failures.**
   - Cover duplicate keys at the root and nested mappings, unsafe/custom tags, malformed syntax, empty and multi-document streams, non-mapping roots, non-string keys, implicit dates/timestamps, non-finite numbers where representable, cyclic aliases, and the chosen alias/merge policy.
   - Cover unknown generator types, invalid nested generator structures, invalid references, missing paths, directories, and unsupported extensions.
   - Assert behavior and `ConfigError` translation, including deck path and useful parser location details, without coupling tests to incidental library exception formatting.

4. **Prove config, CLI, and documentation integration.**
   - Extend workspace tests with relative YAML paths and a JSON/TOML/YAML mixed workspace.
   - Exercise `validate` and `sync` against a YAML-backed deck.
   - Update `README.md` and format-neutral CLI wording to list all supported suffixes, show a minimal YAML example, and describe YAML sequences/mappings plus safety restrictions.
   - Keep existing scaffold files unchanged unless a YAML example template is intentionally added and covered.

5. **Verify and deliver.**
   - Run focused YAML, config, and CLI tests, then `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.
   - Inspect `git status`, exclude unrelated beans, workspaces, databases, caches, and artifacts, check off every acceptance item, append `## Summary of Changes`, mark the bean completed only when all criteria pass, and commit the bean file with its implementation using a subject beginning with the bean ID.

## Test matrix

- Valid: `.yaml`, `.yml`, every generator type, nested metadata, templates, relative paths, mixed formats, CLI validation/sync, and deterministic three-format parity.
- Parser boundary: malformed, empty, multi-document, duplicate keys, custom tags, aliases/cycles, merge policy, unsupported suffix, Unicode, missing/directory/non-regular paths.
- Schema boundary: non-mapping root, missing fields, non-string keys, YAML-native scalar objects, bad generator envelopes, bad nested fields, duplicate IDs, and broken references.
- Invariants: stable parent-directory identity, unchanged display-name behavior, equal card identities and rendered views, and unchanged JSON/TOML/scaffold behavior.
