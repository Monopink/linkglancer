from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Playwright, sync_playwright

from link_glancer.application import TaskApplicationService
from link_glancer.browser.detector import detect_browser
from link_glancer.runtime.dev import JsonlDevLogger, is_dev_mode
from link_glancer.runtime.paths import ensure_browser_environment_dir
from link_glancer.tasks.models import BrowserConfig, TaskItem
from machine_screening.models import MachineScreeningStatus, TikTokVideoStat
from machine_screening.parsers import (
    extract_videos_from_item_list_payload,
    parse_display_play_count,
)
from machine_screening.rules import build_machine_screening_note, evaluate_tiktok_videos

PLAYWRIGHT_ALLOWED_DEFAULT_ARGS = [
    "--no-sandbox",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
]
DEFAULT_PREFETCH_PAGE_COUNT = 2
API_WAIT_SECONDS = 8
DOM_FALLBACK_SECONDS = 20
DOM_VIDEO_SELECTOR = '[data-e2e="user-post-item-list"] strong[data-e2e="video-views"]'


@dataclass(slots=True)
class _PageBufferEntry:
    task: TaskItem
    page: Page


class MachineScreeningSession:
    def __init__(
        self,
        *,
        app_service: TaskApplicationService,
        task_id: int,
        browser_config: BrowserConfig,
        confirm_url: str | None,
    ) -> None:
        self._app_service = app_service
        self._task_id = task_id
        self._browser_config = browser_config
        self._confirm_url = (confirm_url or "").strip() or None
        self._playwright_manager = None
        self._playwright: Playwright | None = None
        self._context = None
        self._confirmation_page: Page | None = None
        self._work_entry: _PageBufferEntry | None = None
        self._prefetch_entries: dict[int, _PageBufferEntry] = {}
        self._items: list[TaskItem] = []
        self._all_target_items: list[TaskItem] = []
        self._paused = True
        self._completed = False
        self._startup_phase = "idle"
        self._last_message = "未启动"
        self._started_at: datetime | None = None
        self._work_started_at: datetime | None = None
        self._captured_videos_by_task_index: dict[int, list] = {}
        self._captured_source_by_task_index: dict[int, str] = {}
        self._dev_logger: JsonlDevLogger | None = None
        self._dom_fallback_started_for_task_index: int | None = None

    def start(self) -> MachineScreeningStatus:
        self.shutdown()
        if is_dev_mode():
            self._dev_logger = JsonlDevLogger(
                module="machine_screening",
                file_stem=f"machine_screening_task_{self._task_id}",
            )
            self._log_event(
                "session_start",
                jsonl_path=str(self._dev_logger.path),
                artifact_dir=str(self._dev_logger.artifact_dir),
            )
        candidate = detect_browser("configured", self._browser_config.executable_path or None)
        if candidate is None:
            self._last_message = "未找到可用浏览器。"
            self._log_event("session_error", reason="browser_not_found")
            return self.status()
        task = self._app_service.load_task(self._task_id)
        items = self._app_service.list_all_items(self._task_id)
        machine_results = self._app_service.list_machine_screening_results(self._task_id)
        self._all_target_items = [
            item
            for item in items
            if str(item.task_data.get(task.task_snapshot.url_field) or "").strip()
        ]
        self._items = [
            item for item in self._all_target_items if item.task_item_id not in machine_results
        ]
        environment_dir = ensure_browser_environment_dir(self._browser_config.profile_id)
        try:
            self._playwright_manager = sync_playwright().start()
            self._playwright = cast(Playwright, self._playwright_manager)
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(environment_dir),
                headless=False,
                executable_path=str(candidate.executable_path),
                args=self._browser_config.launch_args or [],
                ignore_default_args=PLAYWRIGHT_ALLOWED_DEFAULT_ARGS,
            )
            self._context.on("response", self._handle_response)
            self._startup_phase = "browser_confirm"
            self._paused = True
            self._completed = False
            self._started_at = datetime.now(UTC)
            self._last_message = "请确认浏览器状态，确认后将开始自动初筛。"
            self._log_event(
                "browser_started",
                browser_path=str(candidate.executable_path),
                profile_id=self._browser_config.profile_id,
                pending_count=len(self._items),
            )
            self._open_confirmation_page()
        except PlaywrightError as exc:
            self._last_message = f"自动初筛浏览器启动失败：{exc}"
            self._log_event("session_error", reason="browser_launch_failed", details=str(exc))
            self.shutdown()
        return self.status()

    def prepare_pages(self) -> MachineScreeningStatus:
        if self._context is None:
            return self.status()
        self._close_confirmation_page()
        self._startup_phase = "ready"
        self._paused = True
        self._ensure_page_buffer()
        self._last_message = "自动初筛页面已准备。"
        self._log_event(
            "prepare_pages",
            current_task_index=self._work_entry.task.task_index if self._work_entry else None,
            buffered_task_indexes=sorted(self._prefetch_entries),
        )
        return self.status()

    def resume(self) -> MachineScreeningStatus:
        self._paused = False
        if self._work_entry is None:
            self._ensure_page_buffer()
        if self._work_entry is None:
            self._completed = True
            self._last_message = "自动初筛完成。"
            self._log_event("session_completed", reason="no_pending_items")
            return self.status()
        self._startup_phase = "screening"
        self._last_message = "自动初筛运行中。"
        self._log_event("resume", current_task_index=self._work_entry.task.task_index)
        return self.status()

    def stop(self) -> MachineScreeningStatus:
        self._paused = True
        self._last_message = "自动初筛已暂停。"
        self._log_event(
            "pause",
            current_task_index=self._work_entry.task.task_index if self._work_entry else None,
        )
        return self.status()

    def poll(self) -> MachineScreeningStatus:
        if self._context is None or self._paused or self._completed:
            return self.status()
        if self._work_entry is None:
            self._completed = True
            self._last_message = "自动初筛完成。"
            self._log_event("session_completed", reason="work_entry_missing")
            return self.status()
        if self._work_entry.page.is_closed():
            self._paused = True
            self._last_message = "自动初筛页面已关闭。"
            self._log_event(
                "pause",
                reason="work_page_closed",
                task_index=self._work_entry.task.task_index,
            )
            return self.status()
        task_index = self._work_entry.task.task_index
        videos = self._captured_videos_by_task_index.get(task_index)
        if videos:
            self._finalize_current_item(
                videos=videos,
                source=self._captured_source_by_task_index.get(task_index, "api"),
            )
            return self.status()
        if self._work_started_at is None:
            self._work_started_at = datetime.now(UTC)
            return self.status()
        elapsed = (datetime.now(UTC) - self._work_started_at).total_seconds()
        if elapsed >= API_WAIT_SECONDS:
            if self._dom_fallback_started_for_task_index != task_index:
                self._dom_fallback_started_for_task_index = task_index
                self._log_event(
                    "dom_fallback_started",
                    task_index=task_index,
                    elapsed_seconds=elapsed,
                )
            videos = self._extract_dom_videos()
            if videos:
                self._finalize_current_item(videos=videos, source="dom")
                return self.status()
        if elapsed >= DOM_FALLBACK_SECONDS:
            self._finalize_unresolved_current_item("未获取到视频播放量数据。")
        return self.status()

    def status(self) -> MachineScreeningStatus:
        completed_count = len(self._app_service.list_machine_screening_results(self._task_id))
        return MachineScreeningStatus(
            running=self._context is not None,
            paused=self._paused,
            completed=self._completed,
            startup_phase=self._startup_phase,
            total_count=len(self._all_target_items),
            completed_count=completed_count,
            current_task_index=self._work_entry.task.task_index if self._work_entry else None,
            buffered_task_indexes=sorted(self._prefetch_entries),
            last_message=self._last_message,
            started_at=self._started_at,
        )

    def shutdown(self) -> None:
        self._log_event(
            "session_end",
            current_task_index=self._work_entry.task.task_index if self._work_entry else None,
        )
        self._close_confirmation_page()
        for entry in self._prefetch_entries.values():
            self._close_page(entry.page)
        self._prefetch_entries.clear()
        if self._work_entry is not None:
            self._close_page(self._work_entry.page)
            self._work_entry = None
        if self._context is not None:
            try:
                self._context.close()
            except PlaywrightError:
                pass
            self._context = None
        if self._playwright_manager is not None:
            try:
                self._playwright_manager.stop()
            except PlaywrightError:
                pass
            self._playwright_manager = None
        self._playwright = None
        self._paused = True
        self._captured_videos_by_task_index.clear()
        self._captured_source_by_task_index.clear()
        self._work_started_at = None
        self._all_target_items = []
        self._items = []
        self._dom_fallback_started_for_task_index = None
        self._dev_logger = None

    def _open_confirmation_page(self) -> None:
        if self._context is None:
            return
        target_url = self._confirm_url
        if not target_url and self._items:
            task = self._app_service.load_task(self._task_id)
            target_url = str(
                self._items[0].task_data.get(task.task_snapshot.url_field) or ""
            ).strip()
        if not target_url:
            self._log_event("confirmation_page_skipped", reason="no_target_url")
            return
        page = self._context.new_page()
        page.goto(target_url)
        self._confirmation_page = page
        self._log_event("confirmation_page_opened", page_url=target_url)

    def _close_confirmation_page(self) -> None:
        if self._confirmation_page is not None:
            self._log_event(
                "confirmation_page_closed",
                page_url=self._safe_page_url(self._confirmation_page),
            )
            self._close_page(self._confirmation_page)
            self._confirmation_page = None

    def _ensure_page_buffer(self) -> None:
        if self._context is None:
            return
        if self._work_entry is None and self._items:
            work_page = self._context.new_page()
            self._navigate_task_page(work_page, self._items[0])
            self._work_entry = _PageBufferEntry(task=self._items[0], page=work_page)
            self._work_started_at = datetime.now(UTC)
            self._dom_fallback_started_for_task_index = None
            self._log_event(
                "work_page_opened",
                task_index=self._items[0].task_index,
                page_url=self._safe_page_url(work_page),
            )
        desired_prefetch_items = self._items[1 : 1 + DEFAULT_PREFETCH_PAGE_COUNT]
        desired_indexes = {item.task_index for item in desired_prefetch_items}
        for task_index, entry in list(self._prefetch_entries.items()):
            if task_index in desired_indexes:
                continue
            self._log_event(
                "prefetch_page_closed",
                task_index=task_index,
                page_url=self._safe_page_url(entry.page),
            )
            self._close_page(entry.page)
            self._prefetch_entries.pop(task_index, None)
        for item in desired_prefetch_items:
            if item.task_index in self._prefetch_entries:
                continue
            page = self._context.new_page()
            self._navigate_task_page(page, item)
            self._prefetch_entries[item.task_index] = _PageBufferEntry(task=item, page=page)
            self._log_event(
                "prefetch_page_opened",
                task_index=item.task_index,
                page_url=self._safe_page_url(page),
            )

    def _navigate_task_page(self, page: Page, item: TaskItem) -> None:
        task = self._app_service.load_task(self._task_id)
        url = str(item.task_data.get(task.task_snapshot.url_field) or "").strip()
        if url:
            page.goto(url)
            self._log_event("page_navigated", task_index=item.task_index, target_url=url)

    def _handle_response(self, response) -> None:
        response_url = str(getattr(response, "url", ""))
        if "/api/post/item_list/" not in response_url:
            return
        try:
            page = response.frame.page
        except PlaywrightError:
            self._log_event(
                "api_response_ignored",
                reason="page_unavailable",
                response_url=response_url,
            )
            return
        task_index = self._task_index_for_page(page)
        if task_index is None:
            self._log_event(
                "api_response_ignored",
                reason="page_not_owned",
                response_url=response_url,
                page_url=self._safe_page_url(page),
            )
            return
        try:
            payload = response.json()
        except (PlaywrightError, ValueError):
            self._log_event(
                "api_response_parse_failed",
                task_index=task_index,
                response_url=response_url,
            )
            return
        if not isinstance(payload, dict):
            self._log_event(
                "api_response_ignored",
                reason="payload_not_dict",
                task_index=task_index,
                response_url=response_url,
            )
            return
        videos = extract_videos_from_item_list_payload(payload)
        self._log_event(
            "api_response_seen",
            task_index=task_index,
            response_url=response_url,
            video_count=len(videos),
            page_url=self._safe_page_url(page),
        )
        self._write_json_artifact(
            name=f"machine_screening_task_{self._task_id}_item_{task_index}_item_list",
            payload=payload,
        )
        if not videos:
            return
        self._captured_videos_by_task_index[task_index] = videos
        self._captured_source_by_task_index[task_index] = "api"

    def _task_index_for_page(self, page: Page) -> int | None:
        if self._work_entry is not None and page == self._work_entry.page:
            return self._work_entry.task.task_index
        for entry in self._prefetch_entries.values():
            if page == entry.page:
                return entry.task.task_index
        return None

    def _extract_dom_videos(self) -> list[TikTokVideoStat]:
        if self._work_entry is None:
            return []
        try:
            self._work_entry.page.wait_for_selector(DOM_VIDEO_SELECTOR, timeout=1500)
        except PlaywrightError:
            self._log_event(
                "dom_fallback_wait_failed",
                task_index=self._work_entry.task.task_index,
                page_url=self._safe_page_url(self._work_entry.page),
            )
            return []
        try:
            raw_items = self._work_entry.page.evaluate(
                """
                () => {
                    const selector =
                        '[data-e2e="user-post-item-list"] ' +
                        '[data-e2e="user-post-item"] a[href*="/video/"]';
                    const nodes = Array.from(
                        document.querySelectorAll(selector)
                    );
                    return nodes.map((node) => {
                        const viewNode = node.querySelector('strong[data-e2e="video-views"]');
                        const badgeNode = node.querySelector('[data-e2e="video-card-badge"]');
                        return {
                            href: node.getAttribute('href') || '',
                            playCountText: viewNode ? (viewNode.textContent || '') : '',
                            isPinned: Boolean(badgeNode),
                        };
                    });
                }
                """
            )
        except PlaywrightError:
            self._log_event(
                "dom_fallback_eval_failed",
                task_index=self._work_entry.task.task_index,
                page_url=self._safe_page_url(self._work_entry.page),
            )
            return []
        if not isinstance(raw_items, list):
            self._log_event(
                "dom_fallback_invalid_payload",
                task_index=self._work_entry.task.task_index,
                payload_type=type(raw_items).__name__,
            )
            return []
        videos: list[TikTokVideoStat] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            video_id = self._video_id_from_href(str(item.get("href") or "").strip())
            play_count = parse_display_play_count(str(item.get("playCountText") or "").strip())
            if not video_id or play_count is None:
                continue
            videos.append(
                TikTokVideoStat(
                    video_id=video_id,
                    play_count=play_count,
                    is_pinned=bool(item.get("isPinned")),
                )
            )
        self._log_event(
            "dom_fallback_completed",
            task_index=self._work_entry.task.task_index,
            raw_item_count=len(raw_items),
            video_count=len(videos),
            page_url=self._safe_page_url(self._work_entry.page),
        )
        self._write_json_artifact(
            name=f"machine_screening_task_{self._task_id}_item_{self._work_entry.task.task_index}_dom_videos",
            payload={"items": raw_items, "parsed_video_count": len(videos)},
        )
        return videos

    def _finalize_current_item(self, *, videos: list, source: str) -> None:
        if self._work_entry is None:
            return
        task = self._app_service.load_task(self._task_id)
        item = self._work_entry.task
        handle = self._resolve_handle(item)
        evaluation = evaluate_tiktok_videos(
            handle=handle,
            config=task.task_snapshot.machine_screening_config,
            videos=videos,
        )
        machine_note = build_machine_screening_note(evaluation)
        details = dict(evaluation.details)
        details["machine_note"] = machine_note
        details["source"] = source
        details["page_url"] = self._work_entry.page.url
        self._log_event(
            "item_finalized",
            task_index=item.task_index,
            result_code=evaluation.result_code,
            source=source,
            video_count=len(videos),
            page_url=self._safe_page_url(self._work_entry.page),
            machine_note=machine_note,
            evaluation_details=details,
        )
        self._app_service.save_machine_screening_result(
            task_id=self._task_id,
            task_index=item.task_index,
            result_code=evaluation.result_code,
            details=details,
            screened_at=datetime.now(UTC).isoformat(),
        )
        self._last_message = machine_note
        self._advance_after_current()

    def _finalize_unresolved_current_item(self, error_message: str) -> None:
        if self._work_entry is None:
            return
        item = self._work_entry.task
        handle = self._resolve_handle(item)
        machine_note = f"{handle} 自动初筛未完成：{error_message}"
        details = {
            "handle": handle,
            "machine_note": machine_note,
            "source": "unresolved",
            "page_url": self._work_entry.page.url,
        }
        self._log_event(
            "item_unresolved",
            task_index=item.task_index,
            error_message=error_message,
            details=details,
        )
        self._app_service.save_machine_screening_result(
            task_id=self._task_id,
            task_index=item.task_index,
            result_code="screen_unresolved",
            details=details,
            error_message=error_message,
            screened_at=datetime.now(UTC).isoformat(),
        )
        self._last_message = machine_note
        self._advance_after_current()

    def _advance_after_current(self) -> None:
        if self._work_entry is None:
            return
        finished_task_index = self._work_entry.task.task_index
        self._captured_videos_by_task_index.pop(finished_task_index, None)
        self._captured_source_by_task_index.pop(finished_task_index, None)
        current_page = self._work_entry.page
        self._items = [item for item in self._items if item.task_index != finished_task_index]
        promoted_entry = None
        if self._items:
            next_index = self._items[0].task_index
            promoted_entry = self._prefetch_entries.pop(next_index, None)
            if promoted_entry is not None:
                self._log_event(
                    "prefetch_promoted_to_work_page",
                    task_index=next_index,
                    page_url=self._safe_page_url(promoted_entry.page),
                )
        self._close_page(current_page)
        self._work_entry = promoted_entry
        if self._work_entry is None and self._items:
            assert self._context is not None
            page = self._context.new_page()
            self._navigate_task_page(page, self._items[0])
            self._work_entry = _PageBufferEntry(task=self._items[0], page=page)
            self._log_event(
                "work_page_opened",
                task_index=self._items[0].task_index,
                page_url=self._safe_page_url(page),
            )
        self._work_started_at = datetime.now(UTC) if self._work_entry is not None else None
        self._dom_fallback_started_for_task_index = None
        self._ensure_page_buffer()
        if self._work_entry is None:
            self._completed = True
            self._paused = True
            self._startup_phase = "completed"
            self._last_message = "自动初筛完成。"
            self._log_event("session_completed", reason="all_items_processed")

    def _resolve_handle(self, item: TaskItem) -> str:
        raw_handle = str(item.task_data.get("handle") or "").strip()
        if raw_handle:
            return raw_handle.lstrip("@")
        task = self._app_service.load_task(self._task_id)
        url = str(item.task_data.get(task.task_snapshot.url_field) or "").strip()
        if "/@" in url:
            return url.split("/@", 1)[1].split("/", 1)[0].strip()
        return "该达人"

    def _video_id_from_href(self, href: str) -> str:
        path = urlsplit(href).path
        if "/video/" not in path:
            return ""
        return path.rsplit("/video/", 1)[1].split("/", 1)[0].strip()

    def _close_page(self, page: Page) -> None:
        try:
            page.close()
        except PlaywrightError:
            pass

    def _safe_page_url(self, page: Page | None) -> str:
        if page is None:
            return ""
        try:
            return page.url
        except PlaywrightError:
            return ""

    def _log_event(self, event: str, **fields: object) -> None:
        if self._dev_logger is None:
            return
        self._dev_logger.log(
            event,
            task_id=self._task_id,
            startup_phase=self._startup_phase,
            paused=self._paused,
            completed=self._completed,
            current_task_index=self._work_entry.task.task_index if self._work_entry else None,
            buffered_task_indexes=sorted(self._prefetch_entries),
            message=self._last_message,
            **fields,
        )

    def _write_json_artifact(self, *, name: str, payload: object) -> None:
        if self._dev_logger is None:
            return
        path = self._dev_logger.write_text_artifact(
            name=name,
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            extension="json",
        )
        if path is None:
            self._log_event("artifact_write_failed", artifact_name=name)
            return
        self._log_event("artifact_written", artifact_name=name, artifact_path=str(path))
