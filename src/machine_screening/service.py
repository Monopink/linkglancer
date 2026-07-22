from __future__ import annotations

from link_glancer.tasks.models import MachineScreeningRecord, TaskItem, TaskSnapshot
from link_glancer.tasks.screening import (
    is_machine_screening_field,
    normalize_screen_value,
    screen_value_for_result,
)
from machine_screening.models import MachineScreeningSummary


def machine_screening_fields(task_snapshot: TaskSnapshot):
    return [field for field in task_snapshot.review_fields if is_machine_screening_field(field)]


def has_machine_screening_fields(task_snapshot: TaskSnapshot) -> bool:
    return bool(machine_screening_fields(task_snapshot))


def build_machine_screening_summary(
    task_snapshot: TaskSnapshot,
    items: list[TaskItem],
    machine_results: dict[int, MachineScreeningRecord],
) -> MachineScreeningSummary:
    fields = machine_screening_fields(task_snapshot)
    target_items = [
        item for item in items if str(item.task_data.get(task_snapshot.url_field) or "").strip()
    ]
    completed_items = 0
    if fields:
        field = fields[0]
        for item in target_items:
            result = machine_results.get(item.task_item_id)
            value = screen_value_for_result(
                field,
                result.result_code if result is not None else None,
            )
            if normalize_screen_value(field, value) is not None:
                completed_items += 1
    return MachineScreeningSummary(
        field_labels=[field.label for field in fields],
        url_field=task_snapshot.url_field,
        total_items=len(items),
        target_items=len(target_items),
        completed_items=completed_items,
    )
