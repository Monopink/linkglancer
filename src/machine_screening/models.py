from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from link_glancer.tasks.models import MachineScreeningMetricType, MachineScreeningResultCode


@dataclass(slots=True)
class MachineScreeningSummary:
    field_labels: list[str]
    url_field: str
    total_items: int
    target_items: int
    completed_items: int

    @property
    def pending_items(self) -> int:
        return max(self.target_items - self.completed_items, 0)


@dataclass(slots=True)
class TikTokVideoStat:
    video_id: str
    play_count: int
    is_pinned: bool


@dataclass(slots=True)
class MachineScreeningEvaluation:
    result_code: MachineScreeningResultCode
    metric_type: MachineScreeningMetricType
    threshold: int
    top_video_count: int
    used_video_count: int
    excluded_pinned_count: int
    play_counts: list[int]
    computed_value: float | int | None
    details: dict[str, object]


@dataclass(slots=True)
class MachineScreeningStatus:
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
