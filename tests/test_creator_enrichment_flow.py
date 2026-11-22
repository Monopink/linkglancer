from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import Error as PlaywrightError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _load_src_module(module_name: str, relative_path: str):
    package_name = module_name.split(".", 1)[0]
    package_path = SRC_ROOT / package_name
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_path)]
        sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(module_name, SRC_ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {module_name} from {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_src_module("creator_enrichment", "creator_enrichment/__init__.py")
_browser_guard = _load_src_module(
    "creator_enrichment.browser_guard",
    "creator_enrichment/browser_guard.py",
)
_capture_pipeline = _load_src_module(
    "creator_enrichment.capture_pipeline",
    "creator_enrichment/capture_pipeline.py",
)
_contact_badge = _load_src_module(
    "creator_enrichment.contact_badge",
    "creator_enrichment/contact_badge.py",
)
_dialog = _load_src_module(
    "creator_enrichment.dialog",
    "creator_enrichment/dialog.py",
)
_service = _load_src_module(
    "creator_enrichment.service",
    "creator_enrichment/service.py",
)
_version = _load_src_module(
    "creator_enrichment.version",
    "creator_enrichment/version.py",
)

BrowserGuardMixin = _browser_guard.BrowserGuardMixin
CapturePipelineMixin = _capture_pipeline.CapturePipelineMixin
ContactBadgeMixin = _contact_badge.ContactBadgeMixin
CreatorEnrichmentDialog = _dialog.CreatorEnrichmentDialog
CreatorEnrichmentSession = _service.CreatorEnrichmentSession
_CapturedProfile = _capture_pipeline._CapturedProfile


class _FakeAppService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def update_task_item_data(
        self,
        *,
        task_id: int,
        task_index: int,
        task_data_patch: dict[str, object],
    ) -> None:
        self.calls.append(
            {
                "task_id": task_id,
                "task_index": task_index,
                "task_data_patch": task_data_patch,
            }
        )


class _FakeCaptureSession(CapturePipelineMixin):
    def __init__(self) -> None:
        self._app_service = _FakeAppService()
        self._task_id = 7
        self._current_task_index = 1
        self._current_region = "PH"
        self._items_by_index = {
            1: SimpleNamespace(
                task_index=1,
                task_data={"creator_oecuid": "creator-1", "selection_region": "PH"},
            )
        }
        self._captured_profile = _CapturedProfile(
            creator_id="creator-1",
            payload={
                "code": 0,
                "creator_profile": {
                    "creator_oecuid": "creator-1",
                    "bio": "creator bio",
                    "contact_info_available": {
                        "value": True,
                        "is_authorized": True,
                        "status": 0,
                    },
                },
            },
            shop_region="PH",
            profile_types=(1,),
            page_url="https://example.com/detail?cid=creator-1&shop_region=PH",
        )
        self._captured_contact = None
        self._current_step = "waiting_profile"
        self._contact_positive_signal = False
        self._profile_patch_applied = False
        self._last_contact_badge_clicked = False
        self._last_contact_available = None
        self._last_contact_available_raw = None
        self._waiting_started_at = None
        self._last_message = ""
        self.logged_events: list[tuple[str, dict[str, object]]] = []
        self.failed_message: str | None = None

    def _is_task_finalizing(self, task_index: int | None) -> bool:
        return False

    def _advance_to_next_pending(self, *, open_page: bool) -> None:
        raise AssertionError("unexpected advance during profile apply")

    def _log_event(self, event: str, **fields: object) -> None:
        self.logged_events.append((event, fields))

    def _is_captcha_present(self) -> bool:
        return False

    def _pause(self, reason: str, message: str) -> None:
        raise AssertionError("unexpected pause during profile apply")

    def _mark_current_paused(self, paused_status: str) -> None:
        raise AssertionError("unexpected paused state during profile apply")

    def _handle_retryable_manual_failure(self, message: str) -> None:
        self.failed_message = message

    def _refresh_items(self) -> None:
        return

    def _mark_no_contact_and_advance(self) -> None:
        raise AssertionError("unexpected no-contact transition")

    def _with_subject(self, message: str) -> str:
        return message

    def _safe_page_url(self) -> str:
        return "https://example.com/detail?cid=creator-1&shop_region=PH"

    def _click_contact_badge(self) -> bool:
        raise AssertionError("_apply_profile should not click the contact badge directly")

    def _completion_message(self, detail: str | None = None) -> str:
        return CreatorEnrichmentSession._completion_message(self, detail)


class _FakePage:
    def __init__(self, url: str) -> None:
        self._url = url
        self.closed = False
        self.close_calls = 0

    @property
    def url(self) -> str:
        if self.closed:
            raise PlaywrightError("page closed")
        return self._url

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages


class _FakeBrowserGuardSession(BrowserGuardMixin):
    def __init__(self) -> None:
        self.work_page = _FakePage("https://example.com/detail?cid=creator-1&shop_region=PH")
        self.blank_page = _FakePage("about:blank")
        self._context = _FakeContext([self.work_page, self.blank_page])
        self._page = self.work_page
        self._current_task_index = 1
        self._attempt_page_url = ""
        self._page_guard_breached = False
        self._page_guard_breach_reason = ""
        self._collection_mode_installed = False
        self._work_page_task_index = 1
        self._diagnostic_pages: set[int] = set()
        self._last_message = ""
        self.logged_events: list[tuple[str, dict[str, object]]] = []

    def _detail_url_for_task(self, task_index: int | None) -> str:
        return "https://example.com/detail?cid=creator-1&shop_region=PH"

    def _log_event(self, event: str, **fields: object) -> None:
        self.logged_events.append((event, fields))

    def _create_page(self):
        raise AssertionError("unexpected work page recreation")

    def _attach_page_diagnostics(self, page, *, source: str) -> None:
        return

    def _restore_work_page_after_recreation(self, *, reason: str) -> None:
        raise AssertionError("unexpected page recreation restore")

    def _repair_work_page_if_needed(
        self,
        *,
        reason: str,
        task_index: int,
        target_url: str,
    ) -> None:
        return

    def _is_trusted_detail_page(
        self,
        page,
        *,
        task_index: int | None,
        target_url: str | None,
    ) -> bool:
        return page is self.work_page


class _FakeContactBadgeSession(ContactBadgeMixin):
    def __init__(self) -> None:
        self._page = object()
        self._context = None
        self._current_step = "waiting_contact_badge"
        self._captured_contact = None
        self._current_task_index = 1
        self._last_contact_badge_clicked = False
        self._last_contact_badge_detected = False
        self._last_contact_badge_strategy = ""
        self._last_contact_badge_clicked_at = None
        self._contact_badge_click_inflight = False
        self._contact_badge_click_failure_reason = ""
        self._contact_positive_signal = False
        self._page_guard_breached = False
        self._page_guard_breach_reason = ""
        self.logged_events: list[tuple[str, dict[str, object]]] = []
        self.click_calls = 0
        self.stabilize_calls = 0
        self.next_result = {
            "detected": True,
            "clicked": True,
            "strategy": "dom:contact_icon:alliance-icon-email",
            "matched_icon_class": "alliance-icon-email",
            "candidate_count": 1,
            "candidate_summary": "div|f9158724-e9b3-bca4|cursor-pointer",
            "page_count_before": 1,
            "page_count_after": 1,
            "unexpected_new_page": False,
            "page_guard_breach_reason": "",
            "click_error": "",
        }

    def _current_page_matches_current_item(self) -> bool:
        return True

    def _click_contact_badge_via_dom(self) -> dict[str, object]:
        self.click_calls += 1
        return dict(self.next_result)

    def _stabilize_page_after_contact_click(self, *, reason: str) -> None:
        self.stabilize_calls += 1

    def _log_event(self, event: str, **fields: object) -> None:
        self.logged_events.append((event, fields))

    def _safe_page_url(self) -> str:
        return "https://example.com/detail?cid=creator-1&shop_region=PH"


class _FakePopupPage:
    def __init__(self, url: str) -> None:
        self._url = url
        self.closed = False

    @property
    def url(self) -> str:
        if self.closed:
            raise PlaywrightError("page closed")
        return self._url

    def close(self) -> None:
        self.closed = True


class _FakeLocatorList:
    def __init__(self, session: _FakeContactBadgeRealClickSession) -> None:
        self._session = session

    @property
    def first(self) -> _FakeLocatorList:
        return self

    def locator(self, selector: str) -> _FakeLocatorList:
        self._session.locator_calls.append(selector)
        return self

    def count(self) -> int:
        return 1

    def nth(self, index: int) -> _FakeLocatorList:
        self._session.clicked_index = index
        return self

    def click(self, *, timeout: int) -> None:
        self._session.click_timeout = timeout
        if self._session.open_new_page_on_click:
            popup = _FakePopupPage("https://example.com/popup")
            self._session._context.pages.append(popup)
            self._session._page_guard_breached = True
            self._session._page_guard_breach_reason = "context_page_opened"


class _FakeRealClickPage:
    def __init__(self, session: _FakeContactBadgeRealClickSession) -> None:
        self._session = session
        self._url = "https://example.com/detail?cid=creator-1&shop_region=PH"

    @property
    def url(self) -> str:
        return self._url

    def evaluate(self, script: str, params: dict[str, object]) -> dict[str, object]:
        self._session.evaluate_params = params
        return dict(self._session.evaluate_result)

    def locator(self, selector: str) -> _FakeLocatorList:
        self._session.locator_calls.append(selector)
        return _FakeLocatorList(self._session)


class _FakeContactBadgeRealClickSession(ContactBadgeMixin):
    def __init__(self) -> None:
        self._current_step = "waiting_contact_badge"
        self._captured_contact = None
        self._current_task_index = 1
        self._last_contact_badge_clicked = False
        self._last_contact_badge_detected = False
        self._last_contact_badge_strategy = ""
        self._last_contact_badge_clicked_at = None
        self._contact_badge_click_inflight = False
        self._contact_badge_click_failure_reason = ""
        self._contact_positive_signal = False
        self._page_guard_breached = False
        self._page_guard_breach_reason = ""
        self.logged_events: list[tuple[str, dict[str, object]]] = []
        self.locator_calls: list[str] = []
        self.evaluate_params: dict[str, object] | None = None
        self.click_timeout = 0
        self.clicked_index = -1
        self.open_new_page_on_click = True
        self.evaluate_result = {
            "detected": True,
            "clicked": False,
            "strategy": "dom:contact_icon:alliance-icon-email",
            "clickMode": "playwright_locator",
            "candidateIndex": 0,
            "matchedIconClass": "alliance-icon-email",
            "candidate_count": 1,
            "candidate_summary": "div|f9158724-e9b3-bca4|cursor-pointer",
        }
        self._page = _FakeRealClickPage(self)
        self._context = _FakeContext([self._page])

    def _current_page_matches_current_item(self) -> bool:
        return True

    def _stabilize_page_after_contact_click(self, *, reason: str) -> None:
        raise AssertionError("unexpected stabilize on failed click")

    def _log_event(self, event: str, **fields: object) -> None:
        self.logged_events.append((event, fields))

    def _safe_page_url(self) -> str:
        return "https://example.com/detail?cid=creator-1&shop_region=PH"

    def _mark_page_guard_breached(self, reason: str) -> None:
        self._page_guard_breached = True
        self._page_guard_breach_reason = reason


class _FakeDialogResume:
    _resume = CreatorEnrichmentDialog._resume

    def __init__(self, *, attention_required: bool) -> None:
        self._status = SimpleNamespace(attention_required=attention_required)
        self._auto_skip_checkbox = SimpleNamespace(isChecked=lambda: True)
        self.commands: list[dict[str, object]] = []

    def _send_command(self, payload: dict[str, object]) -> None:
        self.commands.append(payload)


class _FakeManualFailureSession:
    _handle_retryable_manual_failure = CreatorEnrichmentSession._handle_retryable_manual_failure
    _classify_failure_issue = CreatorEnrichmentSession._classify_failure_issue
    _pause_issue_for_current = CreatorEnrichmentSession._pause_issue_for_current
    _is_current_page_region_mismatched = CreatorEnrichmentSession._is_current_page_region_mismatched

    def __init__(self, *, auto_skip_on_failure: bool) -> None:
        self._auto_skip_on_failure = auto_skip_on_failure
        self._failure_attempts = []
        self._current_step = "waiting_profile"
        self._task_id = 1
        self._current_task_index = 2
        self._current_region = "PH"
        self._paused = False
        self._pause_reason = None
        self._pause_step = "idle"
        self._issue_code = None
        self._last_message = ""
        self.auto_skipped_messages: list[str] = []
        self.paused_messages: list[str] = []
        self.started_attempts: list[tuple[bool, bool]] = []
        self.captcha_present = False
        self.page_url = "https://example.com/detail?cid=creator-1&shop_region=PH"

    def _build_diagnostic_text(
        self,
        *,
        message: str,
        pause_reason: str | None,
        pause_step: str | None,
    ) -> str:
        return f"{message}|{pause_reason}|{pause_step}"

    def _write_dev_diagnostic_artifact(self, **kwargs) -> None:
        return

    def _mark_current_auto_skipped(self, message: str) -> None:
        self.auto_skipped_messages.append(message)

    def _start_current_attempt(self, *, reload_page: bool, clear_failure_history: bool) -> None:
        self.started_attempts.append((reload_page, clear_failure_history))

    def _pause_manual_for_current(self, message: str) -> None:
        self.paused_messages.append(message)

    def _with_subject(self, message: str) -> str:
        return message

    def _pause(self, reason: str, message: str) -> None:
        self._pause_reason = reason
        self._last_message = message
        self.paused_messages.append(message)

    def _mark_current_paused(self, paused_status: str) -> None:
        return

    def _is_captcha_present(self) -> bool:
        return self.captcha_present

    def _safe_page_url(self) -> str:
        return self.page_url


class _FakeAutoSkipAdvanceSession:
    _mark_current_auto_skipped = CreatorEnrichmentSession._mark_current_auto_skipped
    _pending_items = CreatorEnrichmentSession._pending_items
    _item_state = CreatorEnrichmentSession._item_state

    def __init__(self) -> None:
        self._current_task_index = 2
        self._current_region = "PH"
        self._state = {"statuses": {}}
        self._completed = False
        self._paused = False
        self._pause_reason = None
        self._issue_code = None
        self._attention_event_id = 1
        self._pause_step = "waiting_profile"
        self._current_step = "waiting_profile"
        self._waiting_started_at = object()
        self._items = [
            SimpleNamespace(task_index=2, task_data={"creator_oecuid": "creator-2"}),
            SimpleNamespace(task_index=3, task_data={"creator_oecuid": "creator-3"}),
        ]
        self._finalizing_task_indexes: set[int] = set()
        self._last_message = ""
        self.advance_calls: list[bool] = []
        self.finished_indexes: list[int | None] = []
        self.continued = False

    def _eligible_items(self):
        return list(self._items)

    def _current_subject(self) -> str | None:
        return "creator-2"

    def _persist_state(self) -> None:
        return

    def _advance_to_next_pending(self, *, open_page: bool) -> None:
        self.advance_calls.append(open_page)
        pending_indexes = [item.task_index for item in self._pending_items()]
        if pending_indexes:
            self._current_task_index = pending_indexes[0]
        else:
            self._current_task_index = None

    def _message_for_subject(self, subject: str | None, message: str) -> str:
        if not subject:
            return message
        return f"{subject}：{message}"

    def _finish_task_finalization(self, task_index: int | None) -> None:
        self.finished_indexes.append(task_index)
        self._finalizing_task_indexes.discard(task_index)

    def _continue_after_terminal_transition(self) -> None:
        self.continued = True

    def _begin_task_finalization(self, task_index: int | None) -> None:
        if task_index is not None:
            self._finalizing_task_indexes.add(task_index)


class _FakeTerminalMessageSession:
    _mark_no_contact_and_advance = CreatorEnrichmentSession._mark_no_contact_and_advance
    _completion_message = CreatorEnrichmentSession._completion_message

    def __init__(self, *, completed_after_advance: bool) -> None:
        self._current_task_index = 2
        self._current_region = "PH"
        self._state = {}
        self._completed = False
        self._paused = False
        self._issue_code = None
        self._last_message = ""
        self._continued = False
        self.completed_after_advance = completed_after_advance
        self.persist_calls = 0

    def _begin_task_finalization(self, task_index: int | None) -> None:
        return

    def _current_subject(self) -> str | None:
        return "creator-2"

    def _persist_state(self) -> None:
        self.persist_calls += 1

    def _advance_to_next_pending(self, *, open_page: bool) -> None:
        self._completed = self.completed_after_advance
        if self._completed:
            self._current_task_index = None

    def _message_for_subject(self, subject: str | None, message: str) -> str:
        if not subject:
            return message
        return f"{subject}：{message}"

    def _continue_after_terminal_transition(self) -> None:
        self._continued = True


class _FakeApplyContactSession(CapturePipelineMixin):
    def __init__(self, *, completed_after_advance: bool) -> None:
        self._task_id = 7
        self._current_task_index = 1
        self._current_region = "PH"
        self._state = {}
        self._captured_contact = SimpleNamespace(
            creator_id="creator-1",
            payload={"code": 0, "data": [{"type": 2, "value": "a@example.com"}]},
            page_url="https://example.com/detail?cid=creator-1&shop_region=PH",
        )
        self._items_by_index = {
            1: SimpleNamespace(
                task_index=1,
                task_data={"creator_oecuid": "creator-1", "selection_region": "PH"},
            )
        }
        self._completed = False
        self.completed_after_advance = completed_after_advance
        self._state_updates: list[dict[str, object]] = []
        self._item_updates: list[dict[str, object]] = []
        self._last_message = ""

        class _AppService:
            def __init__(self, outer) -> None:
                self.outer = outer

            def update_task_item_data(self, **kwargs) -> None:
                self.outer._item_updates.append(kwargs)

        self._app_service = _AppService(self)

    def _is_task_finalizing(self, task_index: int | None) -> bool:
        return False

    def _advance_to_next_pending(self, *, open_page: bool) -> None:
        self._completed = self.completed_after_advance
        if self._completed:
            self._current_task_index = None

    def _current_subject(self) -> str | None:
        return "creator-1"

    def _refresh_items(self) -> None:
        return

    def _persist_state(self) -> None:
        return

    def _begin_task_finalization(self, task_index: int | None) -> None:
        return

    def _finish_task_finalization(self, task_index: int | None) -> None:
        return

    def _continue_after_terminal_transition(self) -> None:
        return

    def _message_for_subject(self, subject: str | None, message: str) -> str:
        if not subject:
            return message
        return f"{subject}：{message}"

    def _completion_message(self, detail: str | None = None) -> str:
        return CreatorEnrichmentSession._completion_message(self, detail)

    def _handle_retryable_manual_failure(self, message: str) -> None:
        raise AssertionError(message)

    def _log_event(self, event: str, **fields: object) -> None:
        return


class _FakeIssueDialogHarness:
    _show_issue_dialog_if_needed = CreatorEnrichmentDialog._show_issue_dialog_if_needed
    _issue_dialog_title = CreatorEnrichmentDialog._issue_dialog_title
    _issue_dialog_message = CreatorEnrichmentDialog._issue_dialog_message
    _sync_runtime_options = CreatorEnrichmentDialog._sync_runtime_options

    def __init__(self, status: SimpleNamespace) -> None:
        self._status = status
        self._manual_pause_pending = False
        self._last_issue_dialog_event_id = 0
        self._task = SimpleNamespace(name="task-name")
        self._process = SimpleNamespace(state=lambda: _dialog.QProcess.ProcessState.Running)
        self._auto_skip_checkbox = SimpleNamespace(isChecked=lambda: True)
        self.commands: list[dict[str, object]] = []
        self.simple_dialog_calls: list[tuple[str, str]] = []

    def _send_command(self, payload: dict[str, object]) -> None:
        self.commands.append(payload)

    def _show_simple_issue_dialog(self, *, title: str, message: str) -> str:
        self.simple_dialog_calls.append((title, message))
        return "skip"


class CreatorEnrichmentFlowTests(unittest.TestCase):
    def test_apply_profile_defers_contact_click_to_waiting_contact_badge(self) -> None:
        session = _FakeCaptureSession()

        session._apply_profile()

        self.assertIsNone(session.failed_message)
        self.assertEqual("waiting_contact_badge", session._current_step)
        self.assertTrue(session._profile_patch_applied)
        self.assertEqual(1, len(session._app_service.calls))
        self.assertEqual(
            {
                "bio": "creator bio",
                "contact_info_available": "true",
            },
            session._app_service.calls[0]["task_data_patch"],
        )

    def test_ensure_single_work_page_closes_runtime_blank_page(self) -> None:
        session = _FakeBrowserGuardSession()

        result = session._ensure_single_work_page(reason="runtime_check")

        self.assertTrue(result)
        self.assertIs(session.work_page, session._page)
        self.assertTrue(session.blank_page.closed)
        self.assertEqual(1, session.blank_page.close_calls)

    def test_click_contact_badge_requires_waiting_contact_badge_step(self) -> None:
        session = _FakeContactBadgeSession()
        session._current_step = "waiting_contact"

        result = session._click_contact_badge()

        self.assertFalse(result)
        self.assertEqual(0, session.click_calls)
        self.assertEqual("dom:step_mismatch", session._last_contact_badge_strategy)
        self.assertEqual(
            [
                (
                    "badge_click_skipped",
                    {
                        "task_index": 1,
                        "reason": "step_mismatch",
                        "step": "waiting_contact",
                        "page_url": "https://example.com/detail?cid=creator-1&shop_region=PH",
                    },
                )
            ],
            session.logged_events,
        )

    def test_click_contact_badge_is_one_shot_per_attempt(self) -> None:
        session = _FakeContactBadgeSession()

        first_result = session._click_contact_badge()
        session._current_step = "waiting_contact"
        second_result = session._click_contact_badge()

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(1, session.click_calls)
        self.assertEqual(1, session.stabilize_calls)
        self.assertTrue(session._last_contact_badge_clicked)
        self.assertFalse(session._contact_badge_click_inflight)
        self.assertEqual("badge_click_success", session.logged_events[0][0])
        self.assertEqual("badge_click_skipped", session.logged_events[1][0])
        self.assertEqual("step_mismatch", session.logged_events[1][1]["reason"])

    def test_click_contact_badge_fails_when_new_tab_opens(self) -> None:
        session = _FakeContactBadgeRealClickSession()

        result = session._click_contact_badge()

        self.assertFalse(result)
        self.assertEqual("unexpected_new_page", session._contact_badge_click_failure_reason)
        self.assertFalse(session._last_contact_badge_clicked)
        self.assertEqual(0, session.clicked_index)
        self.assertEqual("unexpected_tab_after_contact_click", session.logged_events[0][0])
        self.assertEqual("badge_click_attempt", session.logged_events[1][0])
        self.assertTrue(session.logged_events[1][1]["unexpected_new_page"])
        self.assertEqual(
            "dom:contact_icon:unexpected_new_page",
            session.logged_events[1][1]["strategy"],
        )

    def test_resume_button_uses_retry_when_attention_is_required(self) -> None:
        dialog = _FakeDialogResume(attention_required=True)

        dialog._resume()

        self.assertEqual(
            [{"cmd": "retry", "auto_skip_on_failure": True}],
            dialog.commands,
        )

    def test_resume_button_passes_auto_skip_on_failure_when_resuming(self) -> None:
        dialog = _FakeDialogResume(attention_required=False)

        dialog._resume()

        self.assertEqual(
            [{"cmd": "resume", "auto_skip_on_failure": True}],
            dialog.commands,
        )

    def test_manual_action_attention_uses_diagnostic_dialog_and_can_skip(self) -> None:
        status = SimpleNamespace(
            current_task_index=1,
            pause_reason="manual_action",
            last_message="资料显示存在联系方式，但页面未出现可点击的联系方式图标，请处理后继续。",
            diagnostic_summary="summary",
            diagnostic_text="details",
            failure_attempts=[{"index": 1, "summary": "s", "diagnostic_text": "d"}],
            attention_required=True,
            attention_event_id=3,
        )
        dialog = _FakeIssueDialogHarness(status)
        original_issue_dialog = _dialog._IssueDialog

        class _FakeIssueDialog:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            def exec_action(self) -> str:
                return "skip"

        _dialog._IssueDialog = _FakeIssueDialog
        try:
            dialog._show_issue_dialog_if_needed()
        finally:
            _dialog._IssueDialog = original_issue_dialog

        self.assertEqual([{"cmd": "skip"}], dialog.commands)
        self.assertEqual(3, dialog._last_issue_dialog_event_id)

    def test_manual_failure_auto_skip_skips_after_retry_limit_when_enabled(self) -> None:
        session = _FakeManualFailureSession(auto_skip_on_failure=True)

        session._handle_retryable_manual_failure("failed")

        self.assertEqual(1, len(session._failure_attempts))
        self.assertEqual([], session.auto_skipped_messages)
        self.assertEqual([(True, False)], session.started_attempts)
        self.assertEqual([], session.paused_messages)

        session._handle_retryable_manual_failure("failed")
        session._handle_retryable_manual_failure("failed")

        self.assertEqual(["failed"], session.auto_skipped_messages)
        self.assertEqual([(True, False), (True, False)], session.started_attempts)

    def test_manual_failure_captcha_never_auto_skips(self) -> None:
        session = _FakeManualFailureSession(auto_skip_on_failure=True)
        session.captcha_present = True

        session._handle_retryable_manual_failure("failed")

        self.assertEqual([], session.auto_skipped_messages)
        self.assertEqual([], session.started_attempts)
        self.assertEqual(["检测到人机验证，请先完成验证后继续。"], session.paused_messages)
        self.assertEqual("captcha", session._pause_reason)

    def test_manual_failure_region_mismatch_never_auto_skips(self) -> None:
        session = _FakeManualFailureSession(auto_skip_on_failure=True)
        session.page_url = "https://example.com/detail?cid=creator-1&shop_region=MY"

        session._handle_retryable_manual_failure("failed")

        self.assertEqual([], session.auto_skipped_messages)
        self.assertEqual([], session.started_attempts)
        self.assertEqual(
            ["当前页面区域与当前数据区域不匹配，请切换到正确页面后继续。"],
            session.paused_messages,
        )
        self.assertEqual("region_mismatch", session._pause_reason)

    def test_auto_skipped_item_is_not_selected_as_pending_again(self) -> None:
        session = _FakeAutoSkipAdvanceSession()

        session._mark_current_auto_skipped("failed")

        self.assertEqual(3, session._current_task_index)
        self.assertEqual([2], session.finished_indexes)
        self.assertTrue(session.continued)
        self.assertEqual("auto_skipped", session._item_state(2)["status"])

    def test_no_contact_final_item_uses_completion_message(self) -> None:
        session = _FakeTerminalMessageSession(completed_after_advance=True)

        original_update_item_state = _service.update_item_state
        _service.update_item_state = lambda *args, **kwargs: None
        try:
            session._mark_no_contact_and_advance()
        finally:
            _service.update_item_state = original_update_item_state

        self.assertEqual(
            "补充采集已全部完成。creator-2没有联系方式。",
            session._last_message,
        )

    def test_apply_contact_final_item_uses_completion_message(self) -> None:
        session = _FakeApplyContactSession(completed_after_advance=True)

        original_contact_patch = _capture_pipeline.contact_patch
        original_update_item_state = _capture_pipeline.update_item_state

        _capture_pipeline.contact_patch = lambda payload, region: SimpleNamespace(
            patch={"email": "a@example.com"},
            total_entries=1,
            valued_entries=1,
            recognized_entries=1,
        )
        _capture_pipeline.update_item_state = lambda *args, **kwargs: None
        try:
            session._apply_contact()
        finally:
            _capture_pipeline.contact_patch = original_contact_patch
            _capture_pipeline.update_item_state = original_update_item_state

        self.assertEqual(
            "补充采集已全部完成。creator-1补充资料已保存。",
            session._last_message,
        )

    def test_captcha_attention_uses_simple_dialog_and_dedupes_by_event_id(self) -> None:
        status = SimpleNamespace(
            current_task_index=1,
            pause_reason="captcha",
            last_message="检测到验证码，请先处理后重试。",
            diagnostic_summary=None,
            diagnostic_text=None,
            failure_attempts=[],
            attention_required=True,
            attention_event_id=5,
        )
        dialog = _FakeIssueDialogHarness(status)

        dialog._show_issue_dialog_if_needed()
        dialog._show_issue_dialog_if_needed()

        self.assertEqual(
            [("需要完成验证码", "请先在浏览器中完成验证，然后重试。")],
            dialog.simple_dialog_calls,
        )
        self.assertEqual([{"cmd": "skip"}], dialog.commands)

        status.attention_event_id = 6
        dialog._show_issue_dialog_if_needed()

        self.assertEqual(2, len(dialog.simple_dialog_calls))
        self.assertEqual([{"cmd": "skip"}, {"cmd": "skip"}], dialog.commands)

    def test_simple_issue_dialog_close_defaults_to_retry(self) -> None:
        harness = _FakeIssueDialogHarness(SimpleNamespace())
        original_message_box = _dialog.QMessageBox

        class _FakeMessageBox:
            Icon = original_message_box.Icon
            ButtonRole = original_message_box.ButtonRole

            def __init__(self, *_args, **_kwargs) -> None:
                self._clicked = None

            def setIcon(self, _icon) -> None:
                return

            def setWindowTitle(self, _title: str) -> None:
                return

            def setText(self, _text: str) -> None:
                return

            def addButton(self, _label: str, _role) -> object:
                return object()

            def exec(self) -> None:
                return

            def clickedButton(self):
                return self._clicked

        _dialog.QMessageBox = _FakeMessageBox
        try:
            action = CreatorEnrichmentDialog._show_simple_issue_dialog(
                harness,
                title="title",
                message="message",
            )
        finally:
            _dialog.QMessageBox = original_message_box

        self.assertEqual("retry", action)

    def test_manual_action_attention_retry_command_is_sent(self) -> None:
        status = SimpleNamespace(
            current_task_index=1,
            pause_reason="manual_action",
            last_message="manual failure",
            diagnostic_summary="summary",
            diagnostic_text="details",
            failure_attempts=[],
            attention_required=True,
            attention_event_id=8,
        )
        dialog = _FakeIssueDialogHarness(status)
        original_issue_dialog = _dialog._IssueDialog

        class _FakeIssueDialog:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            def exec_action(self) -> str:
                return "retry"

        _dialog._IssueDialog = _FakeIssueDialog
        try:
            dialog._show_issue_dialog_if_needed()
        finally:
            _dialog._IssueDialog = original_issue_dialog

        self.assertEqual(
            [{"cmd": "retry", "auto_skip_on_failure": True}],
            dialog.commands,
        )

    def test_sync_runtime_options_sends_set_options_when_worker_running(self) -> None:
        dialog = _FakeIssueDialogHarness(SimpleNamespace())

        dialog._sync_runtime_options()

        self.assertEqual(
            [{"cmd": "set_options", "auto_skip_on_failure": True}],
            dialog.commands,
        )


if __name__ == "__main__":
    unittest.main()
