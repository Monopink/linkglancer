# LinkGlancer

## Purpose
- Build a Windows-first desktop application for human URL review.
- Main workflow: create a task from a source `xlsx`, import rows into SQLite, open URLs in a controlled browser buffer, record human review results, and export a new `xlsx`.
- The application is task-driven. A task is the source workbook plus selected configurations, configuration snapshots, imported rows, review progress, and review results.

## Current Scope
- V1 targets Windows desktop usage.
- V1 focuses on human review.
- V1 input and output format is `xlsx`.

## Fixed Product Decisions
- Tech stack: Python + PySide6 + Playwright + SQLite + openpyxl.
- Browser control is abstracted behind a replaceable layer.
- Browser configurations are application-managed records selected by tasks.
- Browser profiles are managed globally by the application.
- Tasks store configuration snapshots at creation time.
- Review state, task progress, imported rows, configuration records, and snapshots are stored in the application SQLite database.
- Exports always generate a new file.
- Development follows the current task-driven architecture only. Do not add backward compatibility layers, legacy format fallbacks, migration shims, or old-schema readers.

## Development Environment
- Use the repository-local virtual environment at `.venv`.
- Python tool entrypoints run through `.venv`, for example:
  - `.venv\Scripts\python`
  - `.venv\Scripts\python -m ruff check .`
  - `.venv\Scripts\python -m ruff format .`
  - `.venv\Scripts\pre-commit run --all-files`
- `ruff` is the formatter and linter for this repository.
- `pre-commit` stays aligned with the local `.venv` toolchain.
- Before concluding non-trivial code changes, run the relevant local checks through `.venv`.

## Task Model
- A task links to one source `xlsx` file.
- Creating a task immediately imports source rows into SQLite.
- A task uses the current global task configuration, selected browser configuration, and selected review schema.
- A task stores snapshots of the task configuration, browser configuration, and review schema.
- A source file can produce multiple independent tasks with different configurations.
- Continue, restart, jump, pause, review, and export flows read task data from SQLite.

## Configuration System
- Task configuration defines open tab count, selected browser configuration, selected review schema, import fields, export fields, review action shortcuts, confirmation URL, and default export location.
- Browser configurations define executable path, managed profile, launch arguments, test URL, and test status.
- Review schemas define URL field, display fields, review questions, options, and option shortcuts.
- Configuration edits apply to future task creation. Existing tasks use their stored snapshots.

## Review UX Rules
- Main window provides a compact tool-style GUI; browser content stays in a controlled external browser window.
- Main window supports always-on-top with a toggle.
- Top toolbar contains task creation, task continuation, configuration management, task list, and always-on-top controls.
- Start page centers on the task list.
- Task page shows task metadata, progress controls, browser confirmation, and export controls.
- Review page shows a top information bar, current item details, review fields, and submit / previous / revoke / pause actions.
- Buffer size default is 3 tabs/pages.
- Review flow shows total count, completed count, remaining count, and current position.
- Review flow supports continue, restart, and jump-to-index behavior.
- Browser confirmation is required before buffered review begins.
- On submit, the app saves the current result, closes the current browser page, advances the queue, and refills the buffer.
- Review shortcuts apply to review actions.
- Submit action exists and has a shortcut.
- Previous item action exists and has a shortcut.
- Previous item supports review/edit of saved data and keeps browser tab restoration explicit.

## Field System
- The app defines configuration syntax.
- Review schemas define review fields, option shortcuts, and display items. Task configuration defines import and export behavior.
- V1 field types are `single_select`, `multi_select`, `text`, and `boolean`.
- The field model keeps extension space for future automation.
