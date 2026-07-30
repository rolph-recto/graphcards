# Cloze exercises

This template demonstrates the `cloze` exercise type. Store the complete sentence in the entity
field named by `cloze_field`. Mark answers with stable IDs:

```text
The capital of [[c1::France]] is [[c2::Paris]].
```

A string in `entities` selects every marker in that entity. An object selects only the listed
marker IDs. The generator creates one FSRS card for each selected entity. If an entity selects
multiple marker IDs, the first ID in declaration order chooses the stable rendered variant. The
card front hides only that answer. Other answers remain visible. The back shows every answer. All
selected variants for one entity share the entity's FSRS schedule.

Markers can be nested. For example:

```text
([[c1::The answer is [[c2::Answer 1]] NOT CORRECT]])
```

Selecting `c1` hides the complete nested answer. Selecting `c2` keeps the outer text visible and
hides only `c2`.

The same deck content can use JSON, TOML, or YAML. The template includes all three deck files;
`graphcards.toml` uses `deck.json` by default.
