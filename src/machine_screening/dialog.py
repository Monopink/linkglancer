from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QEventLoop, QProcess
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from link_glancer.application import TaskApplicationService
from link_glancer.runtime.dev import dev_mode_title_suffix, is_dev_mode
from link_glancer.runtime.locks import (
    RuntimeLockConflictError,
    RuntimeLockHandle,
    acquire_profile_lock,
    acquire_task_lock,
)
from link_glancer.tasks.models import TaskDetail
from machine_screening.service import build_machine_screening_summary


@dataclass(slots=True)
class _MachineScreeningWorkerStatus:
    running: bool
    paused: bool
    completed: bool
    startup_phase: str
    total_count: int
    completed_count: int
    current_task_index: int | None
    buffered_task_indexes: list[int]
    last_message: str
    started_at: datetime | None

    @classmethod
    def idle(cls) -> _MachineScreeningWorkerStatus:
        return cls(
            running=False,
            paused=True,
            completed=False,
            startup_phase="idle",
            total_count=0,
            completed_count=0,
            current_task_index=None,
            buffered_task_indexes=[],
            last_message="自动初筛会话未启动。",
            started_at=None,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> _MachineScreeningWorkerStatus:
        buffered_task_indexes = payload.get("buffered_task_indexes")
        current_task_index = payload.get("current_task_index")
        return cls(
            running=bool(payload.get("running")),
            paused=bool(payload.get("paused")),
            completed=bool(payload.get("completed")),
            startup_phase=str(payload.get("startup_phase") or "idle"),
            total_count=int(payload.get("total_count") or 0),
            completed_count=int(payload.get("completed_count") or 0),
            current_task_index=(
                int(current_task_index) if isinstance(current_task_index, int) else None
            ),
            buffered_task_indexes=(
                [int(item) for item in buffered_task_indexes if isinstance(item, int)]
                if isinstance(buffered_task_indexes, list)
                else []
            ),
            last_message=str(payload.get("last_message") or ""),
            started_at=_parse_datetime(payload.get("started_at")),
        )


class MachineScreeningDialog(QDialog):
    def __init__(
        self,
        *,
        app_service: TaskApplicationService,
        task: TaskDetail,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_service = app_service
        self._task = task
        self._status = _MachineScreeningWorkerStatus.idle()
        self._startup_pending = True
        self._startup_phase = "browser_confirm"
        self._startup_loop: QEventLoop | None = None
        self._startup_result: bool | None = None
        self._expected_process_exit = False
        self._force_close = False
        self._worker_buffer = ""
        self._process = QProcess(self)
        self._profile_lock: RuntimeLockHandle | None = None
        self._task_lock: RuntimeLockHandle | None = None

        self.setWindowTitle(f"自动初筛 · 任务 #{task.task_id}{dev_mode_title_suffix()}")
        self.resize(480, 280)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._message_label = QLabel()
        self._message_label.setWordWrap(True)
        root.addWidget(self._message_label)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        self._field_label = QLabel("-")
        self._url_label = QLabel("-")
        self._count_label = QLabel("-")
        self._completed_label = QLabel("-")
        self._pending_label = QLabel("-")
        self._current_label = QLabel("-")
        self._buffer_label = QLabel("-")
        form.addRow("初筛列", self._field_label)
        form.addRow("URL 列", self._url_label)
        form.addRow("目标条数", self._count_label)
        form.addRow("已完成", self._completed_label)
        form.addRow("待处理", self._pending_label)
        form.addRow("当前条目", self._current_label)
        form.addRow("缓冲条目", self._buffer_label)
        root.addLayout(form)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._pause_button = QPushButton("暂停")
        self._pause_button.clicked.connect(self._pause)
        self._continue_button = QPushButton("继续")
        self._continue_button.clicked.connect(self._resume)
        buttons.addButton(self._pause_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._continue_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._configure_process()
        self._refresh_summary_labels()
        self._refresh_from_status()

    def start_with_confirmation(self) -> bool:
        if self._summary_target_count() <= 0:
            QMessageBox.information(self, "无可初筛条目", "当前任务没有可用于自动初筛的 URL 条目。")
            return False
        self._startup_result = None
        self._start_worker_process()
        if self._force_close:
            return False
        loop = QEventLoop(self)
        self._startup_loop = loop
        loop.exec()
        self._startup_loop = None
        return bool(self._startup_result)

    def _configure_process(self) -> None:
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.started.connect(self._send_start_command)
        self._process.readyReadStandardOutput.connect(self._read_worker_output)
        self._process.finished.connect(self._handle_process_finished)
        self._process.errorOccurred.connect(self._handle_process_error)

    def _start_worker_process(self) -> None:
        try:
            self._task_lock = acquire_task_lock(
                self._task.task_id,
                owner_label=f"自动初筛任务 - {self._task.browser_config.name}",
            )
            self._profile_lock = acquire_profile_lock(
                self._task.browser_config.profile_id,
                owner_label=f"自动初筛任务 - {self._task.browser_config.name}",
            )
        except RuntimeLockConflictError as exc:
            QMessageBox.warning(self, "无法开始自动初筛", str(exc))
            self._force_close = True
            self.close()
            return
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = ["--machine-screening-worker"]
        else:
            program = sys.executable
            arguments = ["-m", "link_glancer.main", "--machine-screening-worker"]
        if is_dev_mode():
            arguments.append("--dev-mode")
        self._process.start(program, arguments)

    def _send_start_command(self) -> None:
        self._send_command({"cmd": "start", "task_id": self._task.task_id})

    def _read_worker_output(self) -> None:
        self._worker_buffer += bytes(self._process.readAllStandardOutput()).decode(
            "utf-8",
            errors="replace",
        )
        while "\n" in self._worker_buffer:
            line, self._worker_buffer = self._worker_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self._handle_worker_message(payload)

    def _handle_worker_message(self, payload: dict[str, object]) -> None:
        message_type = str(payload.get("type") or "")
        if message_type == "status":
            raw_status = payload.get("status")
            if isinstance(raw_status, dict):
                self._status = _MachineScreeningWorkerStatus.from_payload(raw_status)
                self._maybe_handle_startup_phase()
                self._refresh_summary_labels()
                self._refresh_from_status()
            return
        if message_type == "error":
            self._finish_startup(result=False)
            QMessageBox.warning(
                self,
                "自动初筛失败",
                str(payload.get("message") or "自动初筛失败。"),
            )

    def _maybe_handle_startup_phase(self) -> None:
        if not self._startup_pending:
            return
        phase = self._status.startup_phase or "idle"
        if phase == "browser_confirm" and self._startup_phase == "browser_confirm":
            self._startup_phase = "browser_confirm_shown"
            self._confirm_browser_start()
            return
        if phase == "ready" and self._startup_phase == "browser_confirm_done":
            self._startup_phase = "screening"
            self._startup_pending = False
            self._send_command({"cmd": "resume"})
            self._finish_startup(result=True)

    def _confirm_browser_start(self) -> None:
        result = QMessageBox.question(
            self,
            "确认开始自动初筛",
            "请确认浏览器已正常打开，是否开始自动初筛？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._startup_phase = "browser_confirm_done"
            self._send_command({"cmd": "prepare_pages"})
            return
        self._finish_startup(result=False)
        self._expected_process_exit = True
        self._send_command({"cmd": "shutdown"})
        self._force_close = True
        self.close()

    def _finish_startup(self, *, result: bool) -> None:
        if self._startup_result is None:
            self._startup_result = result
        if self._startup_loop is not None and self._startup_loop.isRunning():
            self._startup_loop.quit()

    def _refresh_summary_labels(self) -> None:
        self._task = self._app_service.load_task(self._task.task_id)
        items = self._app_service.list_all_items(self._task.task_id)
        machine_results = self._app_service.list_machine_screening_results(self._task.task_id)
        summary = build_machine_screening_summary(
            self._task.task_snapshot,
            items,
            machine_results,
        )
        self._field_label.setText("、".join(summary.field_labels) if summary.field_labels else "-")
        self._url_label.setText(summary.url_field or "-")
        self._count_label.setText(f"{summary.target_items} / {summary.total_items}")
        self._completed_label.setText(str(summary.completed_items))
        self._pending_label.setText(str(summary.pending_items))

    def _refresh_from_status(self) -> None:
        status = self._status
        self._message_label.setText(self._display_message_text(status))
        self._current_label.setText(
            str(status.current_task_index) if status.current_task_index else "-"
        )
        self._buffer_label.setText(
            "、".join(str(item) for item in status.buffered_task_indexes) or "-"
        )
        progress_total = max(status.total_count, 1)
        progress_value = min(status.completed_count, progress_total)
        self._progress.setValue(int(progress_value * 100 / progress_total))
        controls_ready = not self._startup_pending
        self._pause_button.setEnabled(
            controls_ready and status.running and not status.paused and not status.completed
        )
        self._continue_button.setEnabled(
            controls_ready and status.running and status.paused and not status.completed
        )

    def _display_message_text(self, status: _MachineScreeningWorkerStatus) -> str:
        if self._startup_pending:
            if self._startup_phase == "browser_confirm_done":
                return "正在准备自动初筛页面。"
            return "正在启动浏览器。"
        return status.last_message or "-"

    def _summary_target_count(self) -> int:
        items = self._app_service.list_all_items(self._task.task_id)
        return sum(
            1
            for item in items
            if str(item.task_data.get(self._task.task_snapshot.url_field) or "").strip()
        )

    def _resume(self) -> None:
        self._send_command({"cmd": "resume"})

    def _pause(self) -> None:
        self._send_command({"cmd": "pause"})

    def _send_command(self, payload: dict[str, object]) -> None:
        if self._process.state() != QProcess.ProcessState.Running:
            return
        self._process.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self._process.waitForBytesWritten(1000)

    def _handle_process_finished(self) -> None:
        self._release_locks()
        self._finish_startup(result=False)
        if self._force_close:
            self._force_close = False
            self.close()

    def _handle_process_error(self, _error: QProcess.ProcessError) -> None:
        if self._force_close or self._expected_process_exit:
            return
        self._finish_startup(result=False)
        QMessageBox.warning(self, "自动初筛进程失败", self._process.errorString())

    def _shutdown_worker_process(self) -> None:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._expected_process_exit = True
        self._send_command({"cmd": "shutdown"})
        if not self._process.waitForFinished(3000):
            self._process.kill()
            self._process.waitForFinished(2000)

    def _release_locks(self) -> None:
        if self._task_lock is not None:
            self._task_lock.release()
            self._task_lock = None
        if self._profile_lock is not None:
            self._profile_lock.release()
            self._profile_lock = None

    def closeEvent(self, event) -> None:
        self._shutdown_worker_process()
        self._release_locks()
        super().closeEvent(event)


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value
