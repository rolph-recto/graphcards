# Capital recall

This template demonstrates an entity-backed analogy generator. Each target entity maps to a source
entity, and the target entity’s direct `front`/`back` fields supply the missing side and answer.
Custom templates receive Entity references and use direct fields such as `source.front` and
`target.back`; every ordinary source field is exposed directly, with no aggregate data mapping.
