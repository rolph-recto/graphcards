---
# graphcards-ixtd
title: Create beans thread workflow skill
status: completed
type: task
priority: normal
created_at: 2026-07-24T21:29:20Z
updated_at: 2026-07-24T21:31:30Z
---

Add a repo-local skill for implementing beans in dedicated worktree threads, looping through review and fix subagents, waiting in the parent thread, and merging the finished branch safely.



## Summary of Changes

- Added `.codex/skills/beans-thread-workflow/SKILL.md` with parent-thread orchestration, child worktree implementation, review/fix loops, bean completion, safe merging, and quality-gate guidance.
- Added `agents/openai.yaml` metadata for explicit `$beans-thread-workflow` invocation.
- Validated the skill with the skill-creator quick validator.



Follow-up refinement: the child thread must mark the bean completed after the final clean review, and the parent thread must ask the user for explicit merge confirmation before merging the child branch.
