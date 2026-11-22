# Creator Enrichment Single-Page Refactor Handoff

Last updated: 2026-07-20

## Purpose

This handoff defines the implementation plan for refactoring `creator enrichment` into a strict single-page browser workflow.

The target is not to patch isolated retry bugs. The target is to remove the leftover multi-tab design entirely and replace it with a single-page runtime model that is easier to reason about, easier to test, and harder to regress.

This work should be implemented without compatibility layers, without placeholder abstractions, and without keeping old multi-tab concepts alive in dead code.

## Background

`creator enrichment` originally started as a single-tab flow, was later pushed toward a multi-tab model, and then partially moved back to single-tab behavior.

The current codebase is in an in-between state:

- User-visible behavior is mostly single-page.
- Runtime structure still contains multi-tab-era concepts.
- Retry and recovery paths still carry the risk of opening additional pages.
- Product configuration still leaks `open_tab_count` into enrichment, even though enrichment no longer meaningfully uses it.

This is the root problem. The bug is architectural, not local.

## Current Situation

Current relevant code areas:

- `src/creator_enrichment/service.py`
- `src/creator_enrichment/worker_main.py`
- `src/creator_enrichment/dialog.py`
- `src/link_glancer/application/services.py`
- `src/link_glancer/tasks/models.py`
- `src/link_glancer/tasks/serialization.py`
- `src/link_glancer/ui/task_creation_dialog.py`

Observed facts from current code:

- `CreatorEnrichmentSession` still accepts `open_tab_count`.
- `CreatorEnrichmentSession` still keeps `_page_entries`, `_current_page_entry`, and `_BufferPage`.
- Methods such as `_sync_visible_buffer`, `_sync_prefetch_pages`, `_open_prefetch_page`, `_close_prepared_page`, `_close_confirmation_page_if_needed` still exist.
- Some of those methods are now no-ops, which means the code has not been structurally simplified.
- Enrichment still launches and controls Playwright directly instead of using a dedicated, minimal single-page browser runtime abstraction.
- Worker startup still passes `task.task_snapshot.open_tab_count` into enrichment.
- Task configuration UI still exposes `open_tab_count` because the general task model also serves manual review buffering.

Conclusion:

- The runtime still thinks in terms of a page buffer even when the behavior mostly uses one page.
- Empty methods and dead state are masking design debt.
- Retry bugs are symptoms of the unresolved runtime model.

## Product Decision

For `creator enrichment`, the browser model is:

- One persistent browser context per enrichment session.
- One application-managed working page per enrichment session.
- Confirmation page and creator detail page share the same page.
- Retry never opens a new page.
- Resume never opens a second working page.
- If the working page is missing or unusable, the runtime must either:
  - recreate exactly one working page, or
  - pause/fail explicitly.
- The enrichment flow must not depend on manual review buffering semantics.

This is a hard rule, not a best-effort guideline.

## Non-Goals

Do not implement any of the following:

- Compatibility wrappers for old multi-tab enrichment behavior
- Feature flags to switch between single-page and multi-tab enrichment
- Transitional methods that keep old buffer/page registry terminology
- Partial cleanup that leaves dead no-op methods behind
- UI behavior that continues to imply enrichment supports configurable tab counts

This refactor should simplify, not preserve history.

## Required Design Outcome

The refactored enrichment runtime should be based on the following conceptual model:

- `browser_context`
- `work_page`
- `current_task_index`
- `attempt_state`
- `session_state`

The following concepts should not exist in enrichment runtime after refactor:

- `open_tab_count`
- buffer pages
- prefetch pages
- page registry
- active page entries
- current page entry
- prepared pages
- visible buffer synchronization

## Architectural Recommendation

### 1. Split browser-page control from enrichment business state

`CreatorEnrichmentSession` currently owns too many responsibilities:

- browser startup
- context/page lifecycle
- navigation
- retry/reload behavior
- enrichment business state machine
- capture processing

This should be simplified.

Recommended outcome:

- `CreatorEnrichmentSession` remains the enrichment business/session coordinator.
- A dedicated internal helper should own strict single-page browser behavior.

Possible shapes:

- a small internal helper class inside `src/creator_enrichment/service.py`, or
- a new dedicated module under `src/creator_enrichment/`

The exact placement is less important than the boundary:

- browser runtime ensures exactly one working page
- enrichment session decides what to do on that page

Do not over-abstract this. A small, concrete helper is preferred over a reusable generic framework.

### 2. Enforce single-page invariants at runtime

On session start, after persistent context launch:

- inspect `context.pages`
- if `0`, create one page
- if `1`, reuse it
- if `>1`, close extras and keep exactly one page

At every critical transition:

- `start`
- `prepare_pages`
- `resume`
- `retry_current`
- polling after browser-side failures

the code must reason in terms of exactly one working page.

### 3. Remove enrichment from `open_tab_count`

`open_tab_count` belongs to manual review/browser buffering, not enrichment.

Required outcome:

- enrichment worker no longer passes `open_tab_count` into session construction
- enrichment session no longer stores or accepts `open_tab_count`
- no enrichment logic depends on task snapshot tab count

If task snapshot continues to store `open_tab_count` for manual review, that is acceptable. But enrichment must stop consuming it.

### 4. Keep confirmation flow on the same page

Current best direction:

- one page opens confirmation URL or first creator detail
- after user confirms, the same page navigates into work
- retry uses `reload` or same-page navigation only

Do not reintroduce a separate confirmation tab.

## Concrete Code Changes

### A. `src/creator_enrichment/service.py`

Primary refactor file.

Required changes:

- Remove `open_tab_count` from `CreatorEnrichmentSession.__init__`.
- Remove `_BufferPage`.
- Remove `_page_entries`.
- Remove `_current_page_entry`.
- Remove `_register_page`, `_entry_for_page`, `_entry_for_task`, `_active_page_entries`, `_unregister_page`.
- Remove `_sync_visible_buffer`.
- Remove `_sync_prefetch_pages`.
- Remove `_prepare_page_for_item`.
- Remove `_close_prepared_page`.
- Remove `_close_confirmation_page_if_needed`.
- Remove `_open_prefetch_page`.
- Simplify `_ensure_current_page` to operate on one page only.
- Simplify `_ensure_runtime_alive` to validate both context and working page assumptions.
- Ensure retry and resume only operate on the single working page.

Recommended runtime helper responsibilities:

- `ensure_context_started`
- `ensure_single_work_page`
- `navigate_work_page`
- `reload_work_page`
- `close_extra_pages`
- `page_is_alive`

Naming can differ, but the responsibility split should stay this small and concrete.

### B. `src/creator_enrichment/worker_main.py`

Required changes:

- Stop passing `task.task_snapshot.open_tab_count` into enrichment session.
- Keep worker command model unchanged unless simplification is obviously beneficial.

### C. `src/creator_enrichment/dialog.py`

Review for behavior only. Major structural change is probably not needed.

Verify:

- no UI copy implies enrichment uses multiple tabs
- issue dialogs still match the new retry behavior
- startup confirmation text remains correct for same-page model

### D. `src/link_glancer/application/services.py`

Required changes:

- Remove enrichment’s dependency on `open_tab_count`.
- Review whether enrichment-specific helpers or defaults still carry multi-tab assumptions.

Important:

- Do not break manual review buffering.
- Only decouple enrichment from that field.

### E. `src/link_glancer/tasks/models.py`

Check whether task model changes are necessary.

Preferred outcome:

- keep `TaskSnapshot.open_tab_count` only if still required by manual review
- do not add enrichment-specific compatibility fields

### F. `src/link_glancer/tasks/serialization.py`

Only change if needed because of model changes.

### G. `src/link_glancer/ui/task_creation_dialog.py`

Do not remove `open_tab_count` from task creation unless product intentionally wants that broader change.

But:

- ensure enrichment-specific UI or copy does not imply this field affects enrichment

If there is enrichment-specific wording tied to tab count, remove or update it.

## Implementation Rules

- Prefer deletion over abstraction.
- Prefer explicit invariants over “soft” behavior.
- Prefer one authoritative working page reference.
- Prefer concrete runtime checks over silent tolerance.

Do not:

- keep empty placeholder methods
- keep unused state for “future flexibility”
- preserve naming from the multi-tab model if the model itself is gone
- create a generic browser framework unless the code genuinely becomes smaller

## Runtime Rules After Refactor

The implementation must satisfy all of the following:

1. `start()` launches a persistent context and settles to exactly one working page.
2. Browser confirmation uses that same working page.
3. `prepare_pages()` does not create a second page.
4. `resume()` does not create a second page.
5. `retry_current()` does not create a second page.
6. Any internal retry path triggered by `_handle_retryable_manual_failure()` does not create a second page.
7. If multiple pages appear in the context, the runtime detects and resolves the situation intentionally.
8. If no page exists, the runtime recreates exactly one page or pauses/fails clearly.

## Logging and Diagnostics

Keep or improve developer diagnostics around page lifecycle.

Recommended diagnostic events:

- session start
- persistent context launched
- page count before normalization
- page count after normalization
- work page created
- work page reused
- extra pages closed
- retry using reload
- retry using same-page navigation
- page unexpectedly missing
- browser/runtime shutdown

This is useful because the current issue is specifically about hidden lifecycle drift.

## Acceptance Criteria

The work is accepted only if all criteria are met.

### Functional

- Starting enrichment opens exactly one application-managed page.
- Confirming startup keeps work on the same page.
- Manual retry never opens an additional page.
- Automatic retry never opens an additional page.
- Resume after pause never opens an additional page.
- Skip and move-to-next still work correctly.
- Completion and shutdown close the browser session cleanly.

### Structural

- No multi-tab enrichment state remains in code.
- No no-op leftover methods remain from the old buffer design.
- Enrichment no longer accepts or stores `open_tab_count`.
- The implementation is smaller and easier to read than before.

### Regression

- Manual review/browser buffer flow remains unaffected.
- Task snapshot serialization remains valid for the rest of the application.

## Test and Verification Plan

There appears to be limited or no automated coverage for enrichment runtime paths. The implementing agent should still add tests where practical, but must at minimum run focused manual verification.

Minimum manual verification:

1. Start enrichment on a task with valid creator detail rows.
2. Confirm browser startup and ensure exactly one page is used.
3. Trigger a manual retry from the issue dialog.
4. Trigger an internal auto retry by forcing a retryable enrichment failure.
5. Pause and resume.
6. Skip current item and continue.
7. Close the browser page unexpectedly and verify runtime handling.
8. Close the whole browser/context and verify runtime handling.
9. Run through completion.

If practical, add targeted tests for:

- page normalization on startup
- retry behavior on single page
- page-loss recovery

## Suggested Execution Order

1. Refactor `src/creator_enrichment/service.py` to remove multi-tab state and methods.
2. Update `src/creator_enrichment/worker_main.py` to stop passing `open_tab_count`.
3. Clean up any application/task coupling that still feeds enrichment tab-count assumptions.
4. Review `dialog.py` copy and control flow for consistency.
5. Run formatting/linting.
6. Run targeted manual verification.

## Relevant Existing Design Docs

- `docs/design/creator-collector/enrichment-flow.md`
- `docs/design/link-glancer/browser-control.md`
- `docs/design/link-glancer/task-configuration.md`

If implementation finds conflicts between current runtime behavior and old notes, prefer the single-page decision in this handoff for enrichment runtime.

## Final Instruction To Implementing Agent

Treat this as a cleanup refactor with functional correction, not as a bugfix patch.

The correct end state is:

- one context
- one work page
- one clear runtime model
- no historical multi-tab leftovers

If a piece of code exists only because enrichment used to support multiple tabs, delete it.
