# Machine Screening Handoff

Last updated: 2026-07-24

## Purpose

This document records the current understanding, design decisions, implementation status, open issues, and next steps for `machine screening` / `自动初筛`.

It is intended as a handoff document for future AI agents or developers who need to:

- understand the product requirements,
- review the current implementation,
- detect design/implementation gaps,
- continue implementation without re-deriving context from chat history.

This document is a working handoff. It is not yet a stable final design spec.

## Background

The project started as a human review tool. The new requirement adds a machine pre-screening stage before human review.

The immediate product target is:

- machine screening opens TikTok creator pages,
- reads creator-side page metrics such as video play counts from the page,
- evaluates each creator against rules,
- records a screening result,
- then human review continues on top of that result,
- and enrichment/export can optionally operate on screened subsets.

The agreed architectural direction is:

- `machine_screening` should be a separate module,
- it should not be tightly coupled into `link_glancer` human review runtime,
- it should also not be folded into `creator_enrichment`,
- `link_glancer` owns task model, field model, range semantics, and review/export/enrichment integration,
- `machine_screening` owns automation/runtime for the automatic screening stage.

The project direction for this work is also explicit:

- no legacy compatibility layer,
- no dead transition code,
- no historical fallback paths,
- database changes must migrate smoothly rather than hard-failing on version mismatch,
- implementation should stay clean even if the feature is only partially complete.

## Product Requirements

### Core screening model

Machine screening is defined as `机器初筛` / `初筛`.

Result domain:

- pass
- fail
- blank / unresolved / not yet screened

Business meaning:

- pass: machine screening passed
- fail: machine screening did not pass
- blank: not screened yet, skipped, or unresolved

### Screening field model

The old `boolean` review field type was removed from the design direction for screening use cases.

A dedicated field type now exists:

- `screen`

Each `screen` field has:

- pass display value
- fail display value
- field source

Current field source values:

- `manual`
- `machine`

Agreed product meaning:

- a machine screening result column is a special system `screen` field,
- its stable identity is application-owned rather than user-defined,
- the current implementation uses a single system field:
  - `field_id = "__machine_screening__"`
  - default label `自动初筛结果`
- human review panel shows that field only after at least one machine-screening result exists,
- human reviewers may edit that machine screening value during review,
- overall screening result is computed by AND semantics across all `screen` fields,
- blank values do not participate in AND evaluation,
- if any resolved screening field is fail, overall result is fail,
- if at least one resolved screening field is pass and none fail, overall result is pass,
- if no screening field has a resolved value, overall result is unresolved.

### Relationship between machine screening and human review

Agreed behavior:

- machine screening runs before human review,
- human review is performed on top of machine screening results,
- if human review has not been run, overall result falls back to machine screening result,
- human review may correct machine screening result manually,
- merged screening value uses:
  - human value first
  - machine value as fallback
- machine-generated values must not mark human review progress as completed.

### Relationship between screening and enrichment/export

Agreed behavior:

- enrichment runs after screening,
- enrichment does not require screening to rerun,
- export and enrichment operate on overall screening result, not only machine result,
- manual review range uses machine-screening-result labels,
- export/enrichment range uses overall-result labels.

### Range semantics

Current configured range values:

- `screen_passed`
- `screen_failed`
- `screen_unresolved`

Current scope configuration areas:

- `manual_review_scope`
- `export_scope`
- `enrichment_scope`

Agreed labels:

- manual review scope:
  - `初筛通过`
  - `初筛不通过`
  - `未初筛`
- export/enrichment scope:
  - `整体通过`
  - `整体不通过`
  - `未筛选`

Agreed semantics:

- `manual_review_scope` filters by the machine-screening system field only,
- `export_scope` filters by overall screening summary across all `screen` fields,
- `enrichment_scope` filters by overall screening summary across all `screen` fields.

### Machine-screening rule config

Current agreed first-version rule:

- target platform: TikTok creator page
- exclude pinned videos
- inspect the first `N` non-pinned videos
- aggregate their play counts with one metric:
  - `sum`
  - `avg`
  - `median`
- compare aggregated value against configured threshold
- `>= threshold` means pass

Agreed first-version inputs:

- `top_video_count`
- `metric_type`
- `play_count_threshold`

Agreed edge-case behavior:

- if non-pinned videos are fewer than `top_video_count`, use the available count,
- if available non-pinned videos are zero, machine screening result is unresolved rather than fail.

### Machine note writing

Agreed behavior:

- machine screening writes:
  - the system machine-screening field
  - a human-readable note into the task remark field
- current default remark field for creator-collection tasks is:
  - `remark`
- machine note updates must not blindly overwrite unrelated human text,
- repeated machine screening on the same item should replace the previous machine-generated note segment,
- machine details remain the canonical structured record in machine-screening storage.

Suggested note examples:

- `@ms.vishop 前10个非置顶视频播放量平均值 1520 >= 1000，自动初筛通过。`
- `@ms.vishop 前10个非置顶视频播放量平均值 820 < 1000，自动初筛不通过。`
- `@ms.vishop 自动初筛未完成：无可用的非置顶视频。`

### Rerun semantics

Agreed behavior from discussion:

- machine screening starts from unresolved items by default,
- if machine screening has already completed for the whole eligible set, starting again should prompt the user,
- after confirmation, rerun should overwrite previous machine screening values.

This behavior is not implemented yet.

### Progress display

Product expectation from discussion:

- task-level progress should eventually separate:
  - machine screening progress,
  - human review progress,
  - enrichment progress.

Emoji-based task list status expansion was explicitly rejected.

Task list status remains only:

- not started
- in progress
- completed

No separate machine-screening task status UI is implemented yet.

## Current Design Decisions

### Module boundary

Current intended boundary:

- `link_glancer`
  - task configuration
  - review field schema
  - screening semantics
  - range filtering
  - export integration
  - human review integration
  - enrichment integration
- `machine_screening`
  - automatic screening runtime
  - page automation
  - page parsing
  - rule evaluation
  - machine-screening session UX/runtime
- `creator_enrichment`
  - creator data enrichment only
  - should not absorb machine-screening responsibilities

### Storage boundary

Current stable direction:

- tasks store screening-related field definitions and range config,
- overall screening summary is computed from merged machine/manual screening values,
- machine screening execution logic remains outside human review runtime,
- machine screening results are stored separately from human `reviews`.

Related note already added in:

- [docs/design/link-glancer/storage-model.md](/D:/Polychrome/Code/Github/link-glancer/docs/design/link-glancer/storage-model.md)

### One machine screening field limit

Current implementation enforces:

- exactly one system-owned machine-screening field in task snapshots

This is an intentional product rule for the current phase.

### Browser control architecture

Agreed runtime direction:

- machine screening should feel similar to human review:
  - buffered browsing
  - current-item-first workflow
- but result collection must remain single-owner and deterministic.

Agreed page-role model:

- one `work_page`
  - the only page allowed to produce a committed machine-screening result
- zero or more `prefetch_page`
  - used only to pre-open later creator pages
  - not allowed to write results directly
- optional `confirmation_page`
  - used before screening session begins

Agreed execution model:

- buffer management may use multiple tabs,
- actual machine screening remains single-page-at-a-time,
- after current item completes, the next prefetch page may be promoted to `work_page`,
- response capture may observe multiple pages, but result application must verify ownership and only commit for the active `work_page`.

## Current Implementation Status

### Implemented: task and field model

Relevant files:

- [src/link_glancer/tasks/models.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/models.py)
- [src/link_glancer/tasks/serialization.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/serialization.py)
- [src/link_glancer/tasks/database.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/database.py)

Implemented:

- `FieldType` now includes `screen`
- `ReviewField` now includes:
  - `screen_pass_value`
  - `screen_fail_value`
  - `source`
- `ReviewFieldSource` exists:
  - `manual`
  - `machine`
- `TaskSnapshot` stores:
  - `manual_review_scope`
  - `export_scope`
  - `enrichment_scope`
- task snapshots now normalize to include the system machine-screening field
- database normalization/migration has been updated to carry the new fields and ranges

### Implemented: screening semantics helper

Relevant file:

- [src/link_glancer/tasks/screening.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/screening.py)

Implemented:

- screening field discovery
- pass/fail/unresolved normalization
- overall screening summary computation
- scope matching
- scope label helpers
- scope normalization

### Implemented: service-layer range wiring

Relevant file:

- [src/link_glancer/application/services.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/application/services.py)

Implemented:

- manual review buffer uses `manual_review_scope`
- manual review count/navigation helpers use `manual_review_scope`
- enrichment eligibility uses `enrichment_scope`
- export uses `export_scope`
- manual review scope now filters by machine-screening value only
- export/enrichment scope use overall screening summary
- merged screening view uses human value first and machine value as fallback
- validation enforces:
  - machine source only allowed on `screen` fields
  - system machine-screening field normalization

### Implemented: human review scope UX wiring

Relevant files:

- [src/link_glancer/ui/main_window.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/ui/main_window.py)
- [src/link_glancer/ui/review_window.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/ui/review_window.py)

Implemented:

- human review button renamed to `人工检查`
- entering review blocks if selected manual scope has no items
- review progress/navigation is based on scoped items rather than raw task indexes
- review page shows `当前检查范围`

### Implemented: task configuration UI for screening

Relevant file:

- [src/link_glancer/ui/task_creation_dialog.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/ui/task_creation_dialog.py)

Implemented:

- review field type includes `筛选`
- task configuration includes multi-select scopes for:
  - manual review
  - export
  - enrichment
- task configuration no longer exposes machine-screening field as a normal editable review field
- non-screen field rows are normalized back to manual source

### Implemented: machine_screening module skeleton

Relevant files:

- [src/machine_screening/__init__.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/__init__.py)
- [src/machine_screening/models.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/models.py)
- [src/machine_screening/service.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/service.py)
- [src/machine_screening/session.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/session.py)
- [src/machine_screening/worker_main.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/worker_main.py)
- [src/machine_screening/parsers.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/parsers.py)
- [src/machine_screening/rules.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/rules.py)
- [src/machine_screening/dialog.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/dialog.py)

Implemented:

- separate module namespace exists
- task-level summary model exists
- service computes:
  - target item counts
  - completed counts based on stored machine-screening rows
- runtime session exists
- worker process and CLI entry exist
- dialog starts the worker and shows progress
- TikTok item-list API parser and DOM fallback parser exist
- rule evaluator exists for `sum` / `avg` / `median`
- main task page has an `自动初筛` button
- button is now shown whenever the task has a URL field

### Implemented: smooth database direction

Relevant file:

- [src/link_glancer/tasks/database.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/database.py)

Current state:

- schema version is currently `9`
- dedicated `machine_screening_results` table exists
- the previous hard incompatibility path was replaced with migration-compatible handling
- existing database reset backup behavior from later merged work remains preserved

## Not Yet Implemented

The following parts are still missing.

### Machine-screening runtime

Partially implemented:

- worker process
- worker entrypoint
- CLI flag in `src/link_glancer/main.py`
- browser confirmation flow
- browser/profile/task lock handling
- long-running session dialog behavior
- pause/continue behavior
- progress push from worker to UI

Still not implemented:

- retry current item
- skip current item
- rerun confirmation and overwrite mode

### TikTok page automation

Partially implemented:

- page navigation to creator detail pages
- API parsing for `item_list`
- DOM fallback parsing for play-count data
- rule engine for pass/fail evaluation

Still not implemented:

- stronger page readiness checks
- error taxonomy for automation failures
- logging/diagnostics comparable to `creator_enrichment`

### Result write path

Partially implemented:

- dedicated write API for machine screening results exists
- merged machine/manual screening read path exists

Still not implemented:

- rerun overwrite behavior
- direct review-row remark patching; current implementation exposes machine note through merged machine/manual view

### Task-level progress split

Not implemented:

- separate task-list display for machine screening progress
- separate task page progress sections for:
  - screening
  - manual review
  - enrichment

## High-Priority Open Issues

### 1. Rerun semantics are discussed but not implemented

Required but missing:

- detect whether all eligible items already have machine-screening result,
- prompt before rerun,
- overwrite previous values after confirmation,
- otherwise default to unresolved-only resume behavior.

### 2. Machine-screening progress and task status are not yet separated

Product expectation exists, implementation does not.

Current task status model still only supports:

- `ready`
- `in_progress`
- `completed`

There is no separate machine-screening status model yet.

## Known Behavior Gaps in Current Code

### Scope wiring is ahead of runtime wiring

The project already supports:

- screening-aware manual scope,
- screening-aware export scope,
- screening-aware enrichment scope,

but machine screening itself still does not run.

That means some of the downstream infrastructure is ready before the upstream producer exists.

### Placeholder dialog can make the feature look more complete than it is

The current `自动初筛` dialog is intentionally skeletal.

It shows:

- field binding
- eligible item counts
- completed counts

But it does not yet:

- launch automation,
- write results,
- or maintain a runtime session.

Agents should not mistake this for an implemented feature.

## Current Relevant Files

Primary implementation areas:

- [src/machine_screening/dialog.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/dialog.py)
- [src/machine_screening/service.py](/D:/Polychrome/Code/Github/link-glancer/src/machine_screening/service.py)
- [src/link_glancer/application/services.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/application/services.py)
- [src/link_glancer/tasks/screening.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/screening.py)
- [src/link_glancer/tasks/models.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/models.py)
- [src/link_glancer/tasks/database.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/database.py)
- [src/link_glancer/tasks/serialization.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/tasks/serialization.py)
- [src/link_glancer/ui/task_creation_dialog.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/ui/task_creation_dialog.py)
- [src/link_glancer/ui/main_window.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/ui/main_window.py)
- [src/link_glancer/ui/review_window.py](/D:/Polychrome/Code/Github/link-glancer/src/link_glancer/ui/review_window.py)
- [src/creator_enrichment/service.py](/D:/Polychrome/Code/Github/link-glancer/src/creator_enrichment/service.py)

Reference docs:

- [docs/design/link-glancer/storage-model.md](/D:/Polychrome/Code/Github/link-glancer/docs/design/link-glancer/storage-model.md)
- [docs/plans/task-config-review-field-refactor.md](/D:/Polychrome/Code/Github/link-glancer/docs/plans/task-config-review-field-refactor.md)
- [docs/plans/creator-enrichment-single-page-refactor-handoff.md](/D:/Polychrome/Code/Github/link-glancer/docs/plans/creator-enrichment-single-page-refactor-handoff.md)

## Recommended Next Steps

### Step 1: confirm the storage strategy before building the worker

This is the highest-priority next decision.

Need to decide:

- should machine screening write into `reviews`,
- if yes, how are human-completion semantics preserved,
- if no, what separate storage shape should exist,
- how does human review load/edit machine-generated values safely.

Recommended outcome:

- define a dedicated machine-screening write/read path before implementing worker automation.

### Step 2: confirm whether machine screen field is preconfigured or runtime-created

Current code assumes preconfiguration.

If product still wants runtime creation, implementation direction needs to change before adding worker logic.

### Step 3: implement runtime session skeleton

Recommended minimum runtime pieces:

- `machine_screening/worker_main.py`
- app CLI entry in `src/link_glancer/main.py`
- session state model
- session dialog with:
  - start
  - progress
  - pause
  - continue
  - retry current
  - stop/close handling
- task/profile lock integration

### Step 4: add a dedicated machine-screening service write API

Avoid calling the human `save_review(...)` path directly from machine automation.

Recommended API direction:

- merge patch only the machine-screening field,
- preserve existing manual fields,
- preserve drafts appropriately,
- keep progress semantics source-aware.

### Step 5: implement TikTok automation last

After storage/runtime decisions are fixed:

- open creator page
- wait for stable page state
- extract page metrics
- evaluate rules
- write pass/fail/blank
- move to next item

This should be done after the data/write semantics are safe.

## Verification Status

At the time of this handoff:

- the codebase passes `ruff check src docs`
- machine-screening runtime has worker/session/API/DOM/rule/write-path basics

## Handoff Summary

What is already solid:

- screening field model
- separate machine-screening storage
- merged machine/manual screening semantics
- range semantics
- downstream scope wiring
- separate module boundary
- task-page entry point

What is still missing:

- runtime/worker session
- TikTok automation
- remark merge/update behavior
- rerun semantics
- task-level split progress

What future agents should do first:

- implement the runtime session and TikTok capture path on top of the already-separated storage model
