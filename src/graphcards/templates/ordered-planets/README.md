# Ordered planets

This workspace demonstrates ordered-list completion cards with the planets in
our solar system.

The RDF graph stores each planet's label and its 1-based position. The query
adds the shared `ex:planets` group, while GraphCards sorts the rows, replaces the
tested planet with `?`, and shows a five-row window around it.

Try it with:

```console
graphcards validate
graphcards study planet-order
```

Set `window_size = 0` in `graphcards.toml` to show the complete list on every
card.
