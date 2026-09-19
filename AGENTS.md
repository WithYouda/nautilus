# Nautilus Agent Instructions

Before making changes in this repository:

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

Repository safety rules:

- Never write access tokens, cookies, API keys, or user content into progress documentation.
- Do not modify existing migrations `001_initial` through `010_ai_conversation_scope`; add future schema changes starting from `011_*.sql` instead.
- Do not use the default `data/` directory for destructive or automated browser tests.
- Do not modify, delete, or stage `diagnostic-backups/`; it is unrelated to Nautilus and may contain sensitive diagnostics.
- Do not use broad staging commands such as `git add .` in this worktree.
- Bind services to `0.0.0.0` and report the WSL2 actual IP in run instructions.
