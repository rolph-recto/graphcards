# Priority-aware capitals

This workspace demonstrates priority-aware multiple-choice distractors.

The RDF data only contains domain facts: countries, capitals, cities, and
labels. Presentation priority lives entirely in the SPARQL query.

The query uses `UNION` to combine four subqueries. Each subquery returns a
different group of choices and binds its own integer `?priority`: correct
answers use zero, the strongest distractors use three, the next tier uses two,
and two tied cutoff distractors use one.

The deck sets `max_choices = 4`, so GraphCards reserves one slot for the
priority-zero correct answer, exhausts priorities three and two, and randomly
selects one of the two priority-one distractors for the final slot. This keeps
choice policy in the deck without adding study-specific metadata to the graph.
Each presentation randomizes candidates within the tied tier, then separately
shuffles all four retained choices, including the correct answer, for display.
The session keeps one random-number stream, so repeated presentations can choose
a different cutoff distractor and display order.

Try it with:

```console
graphcards validate
graphcards study priority-capitals
```
