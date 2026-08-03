# Common relations

This template demonstrates two strict entity-backed `common_relation` generators. Each target maps
directly to an ordered list of related entity IDs. The locations generator uses Europe as its target
and answer. The borders generator uses France as its target and answer. They use separate generator
IDs and distinct targets, so each example has its own scheduled card. Templates can supply any
relationship wording they need. The generator uses `related_label` for related entities and
`answer` for the target, so templates can use `related_entity.related_label` and `target.answer`.
