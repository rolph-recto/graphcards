---
# graphcards-1mgk
title: Inline SPARQL queries in TOML configuration
status: scrapped
type: feature
priority: normal
created_at: 2026-07-24T20:35:15Z
updated_at: 2026-07-28T01:24:38Z
---

Allow SPARQL query text to be embedded directly in graphcards.toml instead of requiring a separate .rq file.

Recommended configuration shape:

```toml
[[decks]]
name = "capitals-basic"
kind = "basic"
target = "triple"
query_inline = """
SELECT ?subject ?predicate ?object ?front ?back
WHERE {
  ?subject <https://example.org/capital> ?object .
  BIND(CONCAT("Capital of ", STR(?subject), "?") AS ?front)
  BIND(STR(?object) AS ?back)
}
"""
```

Requirements:
- Support an inline query field as an alternative to the existing query file path.
- Require exactly one query source per definition: query file or inline text; reject configurations that provide both or neither.
- Preserve existing file-based configuration and resolve file paths relative to the TOML file.
- Validate inline text as a non-empty SPARQL SELECT query when the definition is loaded or first executed, using the same query-contract validation as file queries.
- Preserve useful source context in errors, distinguishing an inline query from a missing/unreadable query file and identifying its deck/source.
- Make inline queries available to built-in and custom card-source/deck definitions, including nested inline sources in the composable-decks configuration.
- Keep query text immutable after configuration loading and avoid writing inline queries to temporary files.
- Update Pydantic configuration models, query execution, tests, README, templates, and example TOML files.
- Document quoting rules, multiline TOML strings, escaping, and the tradeoff between inline and file-based queries.

Design note: use a distinct query_inline field rather than inferring inline text from the existing query field, so paths and SPARQL text remain unambiguous. Revisit a tagged query object or multiline query alias only if the configuration model later needs a broader query-source abstraction.
