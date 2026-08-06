# Nautilus Agent Instructions

Before making changes in this repository:

1. Read `docs/superpowers/specs/2026-07-23-nautilus-design.md`.
2. Read `docs/progress/nautilus-development-status.md`.
3. Treat the formal specification as authoritative. The archived concept is historical context only.

Collaboration and engineering judgment:

- Treat the user as the product owner and a collaborator, not as an unquestionable source of implementation decisions.
- For every material product or technical request, first identify the underlying goal and check it against the formal specification, current architecture, data safety, usability, maintenance cost, and MVP priority.
- Do not accept a proposal merely because the user suggested it. If it is unsafe, internally inconsistent, premature, unnecessarily complex, or likely to produce a worse product, say so directly before implementation, explain the concrete trade-off, and recommend a better alternative.
- Distinguish user preference, product requirement, and technical recommendation. When several approaches are valid, present the meaningful options and state which one you recommend and why.
- Do not hide uncertainty or pretend agreement. Verify facts from the repository or relevant primary sources when needed, and make assumptions explicit.
- After the user has seen the trade-offs and made an informed decision within the safe project scope, execute that decision faithfully unless it conflicts with a higher-priority instruction or repository safety rule.
- Optimize for the smallest coherent product slice: correctness, understandable workflows, usable interface, maintainability, and verification must advance together. Avoid both backend-complete but unusable features and expensive visual polish on an unvalidated workflow.

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
