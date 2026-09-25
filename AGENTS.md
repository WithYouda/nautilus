# Nautilus Agent Instructions

Before making changes in this repository:

The lead agent completes the baseline reading below. Delegated agents read this file and the task-relevant source/specification sections supplied in the handoff; they do not repeat the entire baseline reading unless their scope requires it.

1. Read `docs/superpowers/specs/2026-09-02-nautilus-prd-v2.md` as the current product requirements baseline.
2. Read `docs/superpowers/specs/2026-07-23-nautilus-design.md` for the original product and technical baseline.
3. Read `docs/progress/nautilus-development-status.md`.
4. If working on PRD V2 or the first vertical slice, read `docs/progress/nautilus-prd-v2-review-2026-09-05.md` before proposing changes.
5. Treat the current PRD V2 and confirmed product decision record as authoritative for product direction; the archived concept and superseded portions of the original baseline are historical context only.

Collaboration and engineering judgment:

- Treat the user as the product owner and a collaborator, not as an unquestionable source of implementation decisions.
- For every material product or technical request, first identify the underlying goal and check it against the formal specification, current architecture, data safety, usability, maintenance cost, and MVP priority.
- Do not accept a proposal merely because the user suggested it. If it is unsafe, internally inconsistent, premature, unnecessarily complex, or likely to produce a worse product, say so directly before implementation, explain the concrete trade-off, and recommend a better alternative.
- Distinguish user preference, product requirement, and technical recommendation. When several approaches are valid, present the meaningful options and state which one you recommend and why.
- Do not hide uncertainty or pretend agreement. Verify facts from the repository or relevant primary sources when needed, and make assumptions explicit.
- After the user has seen the trade-offs and made an informed decision within the safe project scope, execute that decision faithfully unless it conflicts with a higher-priority instruction or repository safety rule.
- Optimize for the smallest coherent product slice: correctness, understandable workflows, usable interface, maintainability, and verification must advance together. Avoid both backend-complete but unusable features and expensive visual polish on an unvalidated workflow.

Development agent delegation (confirmed 2026-09-25):

- Prefer `gpt-6-astra` as lead and explicitly select `gpt-6-sol` for bounded delegated tasks when the runtime supports these models. The user authorizes this project workflow without per-task reconfirmation. This governs development tooling, not Nautilus's in-product Provider/model policy. This file does not switch the running lead model; if the requested model or delegation is unavailable, report the limitation and continue with the available lead rather than silently substituting another worker model.
- Astra owns requirement interpretation, product semantics, architecture, data relationships, state machines, cross-module contracts, difficult diagnosis, acceptance criteria, final review, and integration. Sol can implement agreed components/interfaces, fix reproducible local bugs, inspect code, and run or add focused checks within a defined scope. Astra may implement critical logic directly.
- Delegate only when the task has clear boundaries and the expected benefit exceeds handoff/review overhead. Small fixes, short documentation changes, and tightly coupled or still-ambiguous work stay with the lead. Do not force every task into a multi-agent workflow.
- Start with one or two Sol workers; parallelize independent work only. Assign disjoint file ownership, settle shared interfaces first, and serialize overlapping edits. Workers do not recursively delegate unless the lead explicitly assigns that responsibility.
- Each handoff states the goal, relevant files/specification sections, allowed edit scope, agreed interfaces, invariants, acceptance checks, and expected result. Provide the minimum sufficient context instead of copying the entire conversation or all project documents. Workers report missing context or contract conflicts rather than guessing or expanding scope.
- Workers return a concise summary of changes, file references, actual checks/results, and unresolved concerns. The lead reviews the diff and evidence against the acceptance criteria, then performs necessary integration checks; a worker's success claim alone is not acceptance. Reuse valid checks and do not redo the whole task merely to review it.
- If a worker repeatedly misunderstands the task or fails the same acceptance requirement after a focused correction, the lead takes over or changes the decomposition. Do not run an open-ended retry loop to preserve nominally cheaper execution.
- Judge delegation by total task cost, elapsed time, and rework, including lead review and all worker attempts. Use available usage evidence from representative tasks to adjust delegation; do not promise a fixed saving from per-token prices or create a separate reporting bureaucracy.
- The lead owns the final progress/decision updates, local commit, and user report for the combined task. Workers report to the lead without competing progress snapshots or commits unless explicitly assigned otherwise. All existing scope, data-safety, permission, and staging rules apply to every agent.

Product design discussion continuity:

- Treat `docs/progress/nautilus-product-design-decisions.md` as the persistent record of confirmed product direction, architecture principles, and unresolved design questions.
- Before advancing a product discussion, check that document and do not present an already confirmed conclusion as a new open question.
- Whenever a product discussion produces a confirmed material decision, update that document in the same turn, append its update history, and distinguish the confirmed decision from recommendations, open questions, and unimplemented future work.
- Also update `docs/progress/nautilus-development-status.md` so the next Agent can distinguish current code facts from product direction.

Before ending every development turn:

1. Update `docs/progress/nautilus-development-status.md` with the actual implementation status.
2. Record changed files, migrations, tests, known issues, and the exact next task.
3. Append an entry to the document's update history.
4. Do not overstate a vertical slice as a completed product phase.

Proportionate local development:

- After a coherent change passes the relevant checks, create a local Git commit for the reviewed task files unless the user asks to keep it uncommitted. Do not leave completed work uncommitted merely because pushing or publishing would need separate authorization. Exclude unrelated work and private runtime data; use explicit file paths when staging.
- Reuse validation results while the tested code is unchanged. Run focused checks for small changes; broaden testing for shared behavior, data lifecycle changes, failures, or other concrete concerns. Do not rerun a full suite merely to record another handoff or commit.
- Keep the current progress summary short and update it in place; do not prepend competing "latest" snapshots. Record actual changes, checks, limitations, and the next task once. Git preserves the detailed history. Update the product decision record or PRD only when their substance changes; routine fixes do not need a new standalone implementation report.
- UI/code edits and ordinary service restarts do not require database backups. Database version numbers identify schema migrations, not additional environments. Keep using the existing trial environment; the separate rules for real-data migrations, restoration, and destructive operations still apply unless explicitly revised.

Repository safety rules:

- Never write access tokens, cookies, API keys, or user content into progress documentation.
- Do not modify existing migrations `001_initial` through `010_ai_conversation_scope`; add future schema changes starting from `011_*.sql` instead.
- Do not use the default `data/` directory for destructive or automated browser tests.
- Do not modify, delete, or stage `diagnostic-backups/`; it is unrelated to Nautilus and may contain sensitive diagnostics.
- Do not use broad staging commands such as `git add .` in this worktree.
- Bind services to `0.0.0.0` and report the WSL2 actual IP in run instructions.
