# Nautilus Agent Instructions

Before making changes in this repository:

The lead agent completes the baseline reading below. Delegated agents read this file and the task-relevant source/specification sections supplied in the handoff; they do not repeat the entire baseline reading unless their scope requires it.

1. Read `docs/superpowers/specs/2026-09-02-nautilus-prd-v2.md` as the current product requirements baseline.
2. Read `docs/superpowers/specs/2026-07-23-nautilus-design.md` for the original product and technical baseline.
3. Read `docs/progress/nautilus-development-status.md`.
4. If working on PRD V2 or the first vertical slice, read `docs/progress/nautilus-prd-v2-review-2026-09-05.md` before proposing changes.
5. Treat the current PRD V2 and confirmed product decision record as authoritative for product direction; the archived concept and superseded portions of the original baseline are historical context only.
6. Read `docs/superpowers/plans/2026-09-27-nautilus-product-roadmap.md` for the confirmed current sequence and stage boundaries; the older first-slice implementation plan retains detailed contracts, not the future stage order.

Collaboration and engineering judgment:

- Treat the user as the product owner and a collaborator, not as an unquestionable source of implementation decisions.
- For every material product or technical request, first identify the underlying goal and check it against the formal specification, current architecture, data safety, usability, maintenance cost, and MVP priority.
- Do not accept a proposal merely because the user suggested it. If it is unsafe, internally inconsistent, premature, unnecessarily complex, or likely to produce a worse product, say so directly before implementation, explain the concrete trade-off, and recommend a better alternative.
- Distinguish user preference, product requirement, and technical recommendation. When several approaches are valid, present the meaningful options and state which one you recommend and why.
- Do not hide uncertainty or pretend agreement. Verify facts from the repository or relevant primary sources when needed, and make assumptions explicit.
- When any task detail is unclear, first check the confirmed specifications and decisions; if it remains unresolved, ask the user before implementing the dependent behavior. Do not fill the gap with an assumed preference or treat a recommendation as approval. Continue only independent work while awaiting the answer. This clarification rule was explicitly requested by the user on 2026-09-27 and takes precedence over earlier guidance permitting routine choices when those choices remain unclear.
- After the user has seen the trade-offs and made an informed decision within the safe project scope, execute that decision faithfully unless it conflicts with a higher-priority instruction or repository safety rule.
- Optimize for the smallest coherent product slice: correctness, understandable workflows, usable interface, maintainability, and verification must advance together. Avoid both backend-complete but unusable features and expensive visual polish on an unvalidated workflow.

Development agent delegation (confirmed 2026-09-25; quota controls adopted 2026-09-26; worker model updated 2026-10-03):

- Prefer `gpt-6-astra` as lead and explicitly select `gpt-6.1-sol` with `reasoning_effort="xhigh"` for bounded delegated tasks when the runtime supports these models. This worker model/effort supersedes the earlier `gpt-6-sol` / `medium` default at the owner's request on 2026-10-03. The user authorizes this project workflow without per-task reconfirmation. This governs development tooling, not Nautilus's in-product Provider/model policy. This file does not switch the running lead model; if the requested model or delegation is unavailable, report the limitation and continue with the available lead rather than silently substituting another worker model.
- Astra owns requirement interpretation, product semantics, architecture, data relationships, state machines, cross-module contracts, difficult diagnosis, acceptance criteria, final review, and integration. Sol can implement agreed components/interfaces, fix reproducible local bugs, inspect code, and run or add focused checks within a defined scope. Astra may implement critical logic directly.
- Delegate only when the task has clear boundaries and the expected benefit exceeds handoff/review overhead. Small fixes, short documentation changes, and tightly coupled or still-ambiguous work stay with the lead. Do not force every task into a multi-agent workflow.
- Start with one Sol worker; use at most two concurrently by default. A third requires a concrete third independent workstream whose benefit exceeds coordination cost; do not fill slots merely because they are available. Parallelize independent work only. Assign disjoint file ownership, settle shared interfaces first, and serialize overlapping edits. Workers do not recursively delegate unless the lead explicitly assigns that responsibility.
- Each handoff states the goal, relevant files/specification sections, allowed edit scope, agreed interfaces, invariants, acceptance checks, and expected result. Provide the minimum sufficient context instead of copying the entire conversation or all project documents. Workers report missing context or contract conflicts rather than guessing or expanding scope.
- For bounded workers, explicitly pass `fork_turns="none"` and supply the handoff above. Carry a small amount of recent history only when the task depends on it, and explain why; do not inherit the full lead history by default. Model and effort are separate explicit choices, not assumptions based on the model name.
- After a Codex version/environment change, or when behavior suggests an override mismatch, sample actual child `turn_context` model/effort and delegation depth against the spawn request. If they differ, stop expanding concurrency and resolve or report the mismatch. Read only relevant metadata; never commit raw rollouts, credentials, account IDs, or private conversation contents. Do not repeatedly inspect every child after the environment is verified.
- Before integration/browser checks, confirm that the dependent routes and agreed contracts are available in the isolated runtime. A missing route is a readiness issue, not a reason to repeat a whole browser journey. Reuse unchanged checks; batch known fixes before rebuilding, and keep large command output out of the lead context. At a meaningful phase boundary, maintain a compact checkpoint in the development status; do not automatically create a new task or discard useful context.
- Workers return a concise summary of changes, file references, actual checks/results, and unresolved concerns. The lead reviews the diff and evidence against the acceptance criteria, then performs necessary integration checks; a worker's success claim alone is not acceptance. Reuse valid checks and do not redo the whole task merely to review it.
- If a worker repeatedly misunderstands the task or fails the same acceptance requirement after a focused correction, the lead takes over or changes the decomposition. Do not run an open-ended retry loop to preserve nominally cheaper execution.
- Judge delegation by total task cost, elapsed time, and rework, including lead review and all worker attempts. Use available usage evidence from representative tasks to adjust delegation; do not promise a fixed saving from per-token prices or create a separate reporting bureaucracy.
- For the next 3–5 representative real tasks, use a small start/end server-usage sample when available, with actual model/effort, worker count, history mode, result and rework. Compare only reasonably similar tasks; account-wide percentages cannot be attributed entirely to one task. Missing windows remain unknown, and raw rollout token totals are not billing totals. Do not create artificial benchmark tasks or a monitoring system. Any optional controlled comparison stops at 20–30 minutes or 3–5 percentage points of weekly usage, whichever comes first; leave work at a safe checkpoint. Preserve the lead's selected model/effort until evidence supports a change.
- The lead owns the final progress/decision updates, local commit, and user report for the combined task. Workers report to the lead without competing progress snapshots or commits unless explicitly assigned otherwise. All existing scope, data-safety, permission, and staging rules apply to every agent.

Product design discussion continuity:

- **New chat handoffs (owner confirmed 2026-10-03):** When the owner asks to open a new chat, carry forward the source chat's actual current model and reasoning effort. Read the latest available runtime metadata and explicitly pass both values; do not silently use app defaults, a previous turn's model, or this repository's preferred lead model. If the actual values cannot be established, report the missing information before choosing replacements.
- **Project chat names (owner confirmed 2026-10-03):** Use `学海无涯{工作类别}开发{序号}`. While developing functionality, use `学海无涯功能开发N`; the handoff requested on 2026-10-03 is `学海无涯功能开发7`, following `学海无涯功能开发6`. Continue the numbering for later chats, checking existing titles and honoring any explicit name/number from the owner. Do not rename historical chats unless asked.
- New chats receive a compact handoff with the current commit, confirmed decisions, actual validation and trial state, unresolved questions and the exact next task. Create a new chat only when the owner asks; naming/model preferences do not themselves authorize automatic creation. Compaction counts may be checked from available local session metadata; report the observed scope and keep missing records unknown. A suggested count threshold is not an adopted automatic handoff rule.

- Keep the user interface concise and elegant (owner reiterated 2026-10-03). Show useful content and necessary actions by default; put supporting details behind an explicit entry. Do not expose internal version/status terminology, duplicate explanations, or generic disclaimers that do not help the user act. For answer sources, use the requested ellipsis menu after the reply actions and simplify the source view. When the owner asks to review wording first, show the concrete copy/layout before implementing that proposed wording.

- Use plain, familiar language for important user-facing feature names and actions. Describe what the action does; avoid abstract or ceremonial wording such as “正式收尾”. The confirmed goal-management entry is “调整目标状态”, with “已达成”, “暂停目标”, and “停止追踪”; keep labels and explanations consistent.

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

- Prioritize a visible, usable product increment and enable it in the existing trial after relevant checks. Avoid tests that merely mirror implementation, speculative defensive layers, and generic frameworks without a current need; keep checks focused on the changed user journey and its material data boundaries.

- Put delivered native app packages in the dedicated Windows Downloads/Nautilus folder. After the new package for a platform passes its relevant checks, remove superseded Nautilus packages for that platform, including historical copies directly in Downloads. Retain the latest package for each platform; never delete app data, signing keys, backups, or unrelated downloads. Report locked packages that could not be removed rather than claiming cleanup succeeded. This delivery preference was confirmed on 2026-09-29.
- After a coherent change passes the relevant checks, create a local Git commit for the reviewed task files unless the user asks to keep it uncommitted. Do not leave completed work uncommitted merely because pushing or publishing would need separate authorization. Exclude unrelated work and private runtime data; use explicit file paths when staging.
- Reuse validation results while the tested code is unchanged. Run focused checks for small changes; broaden testing for shared behavior, data lifecycle changes, failures, or other concrete concerns. Do not rerun a full suite merely to record another handoff or commit.
- Keep the current progress summary short and update it in place; do not prepend competing "latest" snapshots. Record actual changes, checks, limitations, and the next task once. Git preserves the detailed history. Update the product decision record or PRD only when their substance changes; routine fixes do not need a new standalone implementation report.
- UI/code edits and ordinary service restarts do not require database backups. Database version numbers identify schema migrations, not additional environments. Keep using the existing trial environment; the separate rules for real-data migrations, restoration, and destructive operations still apply unless explicitly revised.

Trial migration authorization (confirmed 2026-09-30):

- The owner identifies the existing `tmp/nautilus-trial-20260919/` environment as development test data and grants standing authorization for ordinary development schema migrations and enabling validated changes there. Do not ask for per-migration authorization again. This supersedes earlier progress/specification text requiring one-time approval for each trial migration.
- Keep the normal migration safeguards: use the established migration tool, retain automatic pre/post-upgrade backups, stop active writes for the upgrade, check data preservation/integrity, and verify the restarted service. Reuse unchanged test evidence. The authorization does not itself request a database wipe, restoration of an older backup, deletion of unrelated files, or migration of a different production environment.

Repository safety rules:

- Never write access tokens, cookies, API keys, or user content into progress documentation.
- Do not modify existing migrations `001_initial` through `010_ai_conversation_scope`; add future schema changes starting from `011_*.sql` instead.
- Do not use the default `data/` directory for destructive or automated browser tests.
- Do not modify, delete, or stage `diagnostic-backups/`; it is unrelated to Nautilus and may contain sensitive diagnostics.
- Do not use broad staging commands such as `git add .` in this worktree.
- Bind services to `0.0.0.0` and report the WSL2 actual IP in run instructions.
