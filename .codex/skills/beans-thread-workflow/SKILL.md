---
name: beans-thread-workflow
description: Implement a GraphCards bean in a dedicated Codex worktree thread, run reviewer and fixer subagent loops until no actionable findings remain, wait for completion from the parent thread, and merge the finished branch safely. Use when a user asks to implement a bean through the project’s thread/worktree/review workflow.
---

# Beans Thread Workflow

Use this workflow when a user asks to implement a bean in a new thread or worktree. Keep the parent thread focused on orchestration and merging; keep implementation, review, fixes, and bean completion inside the child worktree thread.

## Parent thread

1. Run `beans prime` before other bean actions. Search existing beans first with `beans list --json -S "<topic>"` or inspect the requested ID with `beans show --json <id>`. Do not create a duplicate bean.

2. Confirm that the bean is actionable. If it is `draft`, refine it with the user before implementation. Mark the selected bean `in-progress` when work begins.

3. Inspect `git status --short` and preserve unrelated edits. Do not include unrelated generated workspaces, databases, build artifacts, caches, or user files in the child task.

4. Use the Codex app project-thread flow: call `codex_app__list_projects`, then `codex_app__create_thread` with the local project and a new `worktree` target. Use the requested model and reasoning settings when the user specified them. Start from the default branch unless the user explicitly asks to include the current working tree.

5. Give the child thread a complete prompt containing the bean ID, bean requirements, repository instructions, expected quality gates, and the requirement to commit implementation changes plus the bean file. Tell it not to modify unrelated workspaces or files.

6. Wait with `codex_app__wait_threads` using the returned `threadId` and `hostId`. Prefer bounded waits and compact progress snapshots; do not repeatedly read an unchanged thread. If the child requests user input or reports a blocker, surface it instead of merging.

7. When the child finishes, inspect its final report, branch, and worktree. Confirm that the child marked the bean `completed`, appended a `## Summary of Changes` section, and committed only scoped changes.

8. Before merging, check the parent worktree for conflicts and preserve unrelated changes. Tell the user the child is complete, identify the child branch/worktree and commit, summarize the review/test result, and ask for explicit confirmation to merge. Do not merge until the user confirms. If the user declines or does not confirm, leave the child branch/worktree intact and report how to resume.

9. After confirmation, identify the child branch with `git worktree list`, then merge it into the parent using ordinary non-destructive Git commands. Never reset or checkout away user changes.

10. After merging, inspect `git status --short`, verify the merge commit or fast-forward, and run the relevant quality gates in the parent worktree. Report the merged commit and any intentionally unmerged or untracked files.

## Child implementation thread

1. Read `AGENTS.md`, run `beans prime`, inspect the selected bean, and update it to `in-progress` if the parent has not already done so. Use the bean as the work tracker; do not create a separate task list.

2. Work only in the assigned worktree. Make a concise implementation plan, preserve unrelated files, and follow the repository’s Pydantic, error-translation, `uv`, and quality-gate requirements.

3. Implement the bean completely, including behavior, tests, documentation, and configuration changes required by the bean. Test behavior rather than compatibility details unless the bean explicitly requires compatibility.

4. Run focused tests while iterating, then run the repository quality gates: `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`. Remove or ignore generated artifacts appropriately.

## Review/fix loop

After implementation and initial tests, spawn independent review subagents for bounded passes such as:

- behavioral correctness and bean requirements;
- tests, regressions, and edge cases;
- error handling, configuration, and security;
- API, documentation, and quality-gate completeness.

Give reviewers the implementation diff and bean requirements, but ask for findings rather than leading them toward a suspected issue. Reviewers must classify findings as actionable or no finding and cite files and lines.

For each actionable finding, spawn or assign a fixer subagent with the exact finding and acceptance condition. Inspect the fixer’s changes, rerun focused tests and quality checks, then repeat the review passes. Continue until all reviewers report no actionable findings or a genuine external blocker is documented; do not stop after one nominal review round.

After the final clean review, update the bean with `## Summary of Changes`, mark it `completed`, and commit the scoped implementation and bean file. Include test results in the child final report so the parent can verify them. The child must not wait for or request merge confirmation; the parent asks the user after inspecting the completed child.

## Safety and handoff

- Treat existing uncommitted files as user-owned. Stage explicit scoped paths only.
- Do not delete worktrees, branches, databases, or generated directories unless the user explicitly requests cleanup.
- If a review finding repeats without progress, or a required external state change is unavailable, report the blocker to the parent rather than hiding it.
- The parent owns the final merge; the child must not merge its own worktree into the parent.
