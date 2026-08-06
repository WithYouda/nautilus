# Nautilus Plan Information Architecture Implementation Plan

> **Status:** Completed on 2026-08-05. Final verification: backend `114 passed`, production build succeeded, Playwright `31 passed`, and isolated Chromium checks passed at `1440x1000`, `1024x640`, and `390x844`.

> **For agentic workers:** Execute this plan task-by-task with tests first. Repository instructions prohibit commits unless the user explicitly requests one, so commit steps are intentionally omitted.

**Goal:** Replace the current first-plan editor with a scalable plan overview/detail workflow, reversible task completion, document-style inline editing, and persisted global/plan/task AI context scopes.

**Architecture:** Keep the FastAPI modular monolith and existing React workspace shell. Add summary/detail/schedule read models and two forward-only SQLite migrations, split the plan frontend into focused view components, and extend the existing conversation runtime with a persisted scope discriminator rather than creating new AI services.

**Tech Stack:** FastAPI, SQLite migrations, Pydantic, React, TypeScript, Vite, Lucide, pytest, Playwright.

---

## File Map

- Create `backend/app/migrations/009_task_completion_restore.sql`: reversible completion storage.
- Create `backend/app/migrations/010_ai_conversation_scope.sql`: persisted conversation/snapshot scope.
- Modify `backend/app/plans.py`: summary/detail/schedule queries, stable next-task ordering, reversible completion.
- Modify `backend/app/schemas.py`: completion command and scoped conversation request schemas.
- Modify `backend/app/routers/plans.py`: new plan read APIs and completion endpoint.
- Modify `backend/app/conversations.py`: scoped context previews, links, list/detail recovery, frozen snapshots.
- Modify `backend/app/routers/ai.py`: scoped conversation creation and context preview endpoints.
- Modify `backend/tests/test_plans.py`: migration, summary, schedule and completion regressions.
- Modify `backend/tests/test_ai_conversations.py`: scope migration, creation, recovery and snapshot regressions.
- Modify `frontend/src/api.ts`: plan read models, completion command and AI scope types.
- Create `frontend/src/PlanWorkspace.tsx`: plan list/detail navigation and URL restoration.
- Create `frontend/src/PlanOverview.tsx`: stacked subject progress and recent tasks.
- Create `frontend/src/PlanStructure.tsx`: progressive disclosure and single movable inline editor.
- Create `frontend/src/PlanSchedule.tsx`: plan-scoped date groups and rescheduling.
- Create `frontend/src/UnsavedChangesDialog.tsx`: save/discard/continue guard.
- Modify `frontend/src/PlanEditor.tsx`: retain focused editor form primitives and remove old split-pane orchestration.
- Modify `frontend/src/Workspace.tsx`: use plan summaries/detail loading and scoped AI entry state.
- Modify `frontend/src/AiCompanionPanel.tsx`: global/plan/task context presentation.
- Modify `frontend/src/AiLearningRoom.tsx`: scope-aware creation, recovery, history labels and context display.
- Rewrite `frontend/src/styles/plan-editor.css`: overview list, detail shell, outline, inline editor and responsive drawer styles.
- Modify `frontend/src/styles/v6-workspace.css` and `frontend/src/styles/ai-learning.css`: scoped companion/drawer integration only.
- Create `frontend/e2e/plan-workspace.spec.ts`: plan workflow and responsive browser coverage.
- Modify `frontend/e2e/ai-learning.spec.ts`: global/plan/task scope persistence coverage.
- Modify `docs/progress/nautilus-development-status.md`: actual implementation and verification record.

## Task 1: Baseline and 009 Migration Tests

- [x] Add failing tests to `backend/tests/test_plans.py` asserting migrations end in `009_task_completion_restore` and `010_ai_conversation_scope` only after both tasks are implemented.
- [x] Add failing tests for `PUT /api/tasks/{id}/completion`:
  - pending/37 -> completed/100 -> pending/37;
  - in_progress/61 -> completed/100 -> in_progress/61 without reviving a study session;
  - repeated complete does not overwrite restore values;
  - legacy completed rows restore to pending/0;
  - actual minutes and completed study sessions are unchanged by undo.
- [x] Run `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_plans.py -q` and confirm the new cases fail because the migration/API do not exist.
- [x] Create `009_task_completion_restore.sql` with nullable `completion_restore_status` and `completion_restore_progress` columns and valid CHECK constraints.
- [x] Add `TaskCompletionRequest(completed: bool)` and route `PUT /api/tasks/{task_id}/completion`.
- [x] Refactor `PlanService.complete_task` into idempotent `set_task_completion(identity_id, task_id, completed)`; keep the old POST route delegating to `completed=True`.
- [x] Update active timer discovery to query active `study_session` rows directly rather than assuming every `in_progress` task has a live timer.
- [x] Run the directed plan tests until all completion cases pass.

## Task 2: Plan Summary, Detail and Schedule Read Models

- [x] Add failing backend tests for `GET /api/plans/summary`, `GET /api/plans/{goal_id}` and `GET /api/plans/{goal_id}/schedule`.
- [x] Cover progress denominator rules, soft-deleted/canceled exclusions, empty plans, active timer priority, overdue priority and deterministic tie-breaking.
- [x] Add `PlanService.list_plan_summaries`, `get_plan_detail` and `plan_schedule` using SQL aggregation rather than loading all trees for the summary page.
- [x] Return summary fields: counts, completed count, progress, estimated/actual minutes and a fully contextualized `next_task`.
- [x] Keep `GET /api/plans` unchanged for existing callers while new frontend code migrates to the new APIs.
- [x] Run `backend/tests/test_plans.py` and confirm the old plan CRUD/timer tests remain green.

## Task 3: Plan Frontend Data Boundary and Navigation

- [x] Extend `frontend/src/api.ts` with `PlanSummary`, `PlanDetail`, `SubjectProgress`, `PlanScheduleItem`, `getPlanSummaries`, `getPlan`, `getPlanSchedule` and `setTaskCompletion`.
- [x] Create `PlanWorkspace.tsx` with explicit list/detail state:
  - list is the first plan screen;
  - opening a row defaults to overview;
  - opening next task forces structure and target node;
  - `view=plans`, `plan`, `tab` and `node` are synchronized through History API;
  - invalid IDs fall back to the list with an error message.
- [x] Update `Workspace.tsx` so the initial workspace load no longer requires all plan trees; selected task fallback comes from dashboard/tasks instead.
- [x] Ensure plan creation opens the created plan detail while preserving existing PlanDialog behavior.
- [x] Run the frontend production build and fix all strict TypeScript errors before styling.

## Task 4: Overview and Schedule Views

- [x] Create `PlanOverview.tsx` with a compact metric strip, full-width subject progress rows, and a separate full-width recent-task section below it.
- [x] Wire task open, reversible completion and task AI actions without changing the plan companion scope.
- [x] Create `PlanSchedule.tsx`, group tasks by date, and reuse the existing reschedule endpoint for +/- day operations.
- [x] Add the global calendar handoff with a plan filter encoded in workspace state/URL.
- [x] Add loading, empty and mutation error states for each subview independently.

## Task 5: Document-Style Structure and Inline Editing

- [x] Create `PlanStructure.tsx` with top-level subjects always visible and subject/topic expansion controlled by separate chevron buttons.
- [x] Restore valid expanded IDs from `sessionStorage` per plan; on first entry expand only the target/next-task ancestor path.
- [x] Implement one `TaskOutlineItem` primary action:
  - click closed task -> open editor below it;
  - click current task -> close editor;
  - click another task -> close current and move the single editor below the new task;
  - checkbox, task AI and overflow actions do not toggle editing.
- [x] Add subject/topic inline forms, task form reuse, parent-owned add buttons, and low-frequency reorder/delete menus.
- [x] Create `UnsavedChangesDialog.tsx`; guard node switches, adds, tab changes, back navigation and AI entry with save/discard/continue.
- [x] Register `beforeunload` only while the current editor is dirty.
- [x] Replace the old permanent split-pane styles with the document outline styles and verify long names wrap or truncate without moving controls.

## Task 6: 010 Conversation Scope Migration and Backend Runtime

- [x] Add failing tests for the `010` migration backfill:
  - existing task-linked conversations become `task`;
  - existing unlinked conversations remain `independent`;
  - no existing rows become `global` automatically.
- [x] Create `010_ai_conversation_scope.sql`, adding `conversation.context_scope` and `context_snapshot.scope_kind` with allowed values `independent/global/plan/task` plus indexes/backfill.
- [x] Replace task-only creation input with explicit `context_scope` and `target_id`, while retaining legacy `task_id` compatibility.
- [x] Add `global_context`, `plan_context` and unified `context_for_conversation`; keep task context behavior compatible.
- [x] Persist a primary goal link for plan conversations and a primary task link for task conversations; global/independent conversations remain unlinked but distinct by scope.
- [x] Freeze `scope_kind`, bounded payload metadata and truncation indicators in every context snapshot.
- [x] Extend list/detail results with scope and target information and verify deleted target behavior remains readable.
- [x] Run `backend/tests/test_ai_conversations.py` plus `backend/tests/test_plans.py`.

## Task 7: Scoped Companion and Learning Room

- [x] Extend the AI room session state with `contextScope` and `targetId`; task entry clears stale conversation/run state as before.
- [x] Update `AiCompanionPanel` props from `task` to a discriminated context object:
  - plan list/today/task/calendar default to global;
  - plan detail defaults to plan;
  - explicit task AI uses task.
- [x] Update `AiLearningRoom` to restore the most recent valid conversation matching the entry scope/target and create new conversations with the same scope.
- [x] Show global/plan/task/independent labels in history and current conversation information without adding status text back into the centered title bar.
- [x] Preserve provider/model configuration, title generation, deletion confirmation and task-context regression behavior.

## Task 8: Automated and Browser Verification

- [x] Add `frontend/e2e/plan-workspace.spec.ts` covering plan list first screen, overview stacking, title-owned add subject, focus expansion, task-row single-open behavior, unsaved guard and reversible completion.
- [x] Extend AI E2E coverage for global -> plan -> task entry, new conversation inheritance, return/reload restoration and independent conversation isolation.
- [x] Assert task checkbox/task AI/overflow controls do not toggle the inline editor.
- [x] Verify `1440x1000`, `1024x640` and `390x844` have no page-level overflow or overlapping controls.
- [x] Run directed backend tests, full backend pytest, production build, directed Playwright and full Playwright.
- [x] Run script syntax/safety checks, `pip check` and `git diff --check`.
- [x] Start a new isolated production preview under `/tmp/nautilus-*`, inspect real Chromium screenshots at all three viewports, and leave the verified URL running for user review.
- [x] Update `docs/progress/nautilus-development-status.md` with changed files, migrations, exact test results, known risks and the next task.
