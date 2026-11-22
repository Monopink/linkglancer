from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from link_glancer.tasks.database import (
    list_all_items,
    list_machine_screening_results,
    list_reviews,
    load_task_detail,
)
from link_glancer.tasks.export_fields import resolve_export_fields
from link_glancer.tasks.models import MachineScreeningRecord, ReviewRecord, TaskItem, TaskSnapshot
from link_glancer.tasks.screening import (
    machine_remark_field,
    machine_screening_field,
    matches_screening_scope,
    screen_value_for_result,
)


def export_task_results(
    database_path: Path, task_id: int, destination_dir: Path | None = None
) -> Path:
    task = load_task_detail(database_path, task_id)
    items = list_all_items(database_path, task_id)
    reviews_by_item_id = list_reviews(database_path, task_id)
    machine_results = list_machine_screening_results(database_path, task_id)
    items = [
        item
        for item in items
        if matches_screening_scope(
            task.task_snapshot,
            _merged_review_data(
                task.task_snapshot,
                review=reviews_by_item_id.get(item.task_item_id),
                machine_screening=machine_results.get(item.task_item_id),
            ),
            task.task_snapshot.export_scope,
        )
    ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    export_fields = resolve_export_fields(
        task.task_snapshot.review_fields,
        task.task_snapshot.enabled_review_field_ids,
        items,
        task.task_snapshot.export_fields,
    )
    machine_field = machine_screening_field(task.task_snapshot)
    if machine_field is not None and not machine_results:
        export_fields = [
            field_name for field_name in export_fields if field_name != machine_field.field_id
        ]

    for column_index, export_field in enumerate(export_fields, start=1):
        sheet.cell(row=1, column=column_index, value=export_field)

    for row_index, item in enumerate(items, start=2):
        review = reviews_by_item_id.get(item.task_item_id)
        machine_result = machine_results.get(item.task_item_id)
        for column_index, export_field in enumerate(export_fields, start=1):
            value = _resolve_export_value(
                export_field,
                item,
                task.task_snapshot,
                review,
                machine_result,
            )
            if isinstance(value, list):
                value = ", ".join(str(option) for option in value)
            sheet.cell(row=row_index, column=column_index, value=value)

    export_dir = destination_dir or task.source_file_path.parent
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = _safe_filename(task.name)
    export_path = _unique_export_path(export_dir / f"{safe_name}_{timestamp}.xlsx")
    workbook.save(export_path)
    workbook.close()
    return export_path


def export_task_results_to_path(database_path: Path, task_id: int, export_path: Path) -> Path:
    task = load_task_detail(database_path, task_id)
    items = list_all_items(database_path, task_id)
    reviews_by_item_id = list_reviews(database_path, task_id)
    machine_results = list_machine_screening_results(database_path, task_id)
    items = [
        item
        for item in items
        if matches_screening_scope(
            task.task_snapshot,
            _merged_review_data(
                task.task_snapshot,
                review=reviews_by_item_id.get(item.task_item_id),
                machine_screening=machine_results.get(item.task_item_id),
            ),
            task.task_snapshot.export_scope,
        )
    ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    export_fields = resolve_export_fields(
        task.task_snapshot.review_fields,
        task.task_snapshot.enabled_review_field_ids,
        items,
        task.task_snapshot.export_fields,
    )
    machine_field = machine_screening_field(task.task_snapshot)
    if machine_field is not None and not machine_results:
        export_fields = [
            field_name for field_name in export_fields if field_name != machine_field.field_id
        ]

    for column_index, export_field in enumerate(export_fields, start=1):
        sheet.cell(row=1, column=column_index, value=export_field)

    for row_index, item in enumerate(items, start=2):
        review = reviews_by_item_id.get(item.task_item_id)
        machine_result = machine_results.get(item.task_item_id)
        for column_index, export_field in enumerate(export_fields, start=1):
            value = _resolve_export_value(
                export_field,
                item,
                task.task_snapshot,
                review,
                machine_result,
            )
            if isinstance(value, list):
                value = ", ".join(str(option) for option in value)
            sheet.cell(row=row_index, column=column_index, value=value)

    export_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(export_path)
    workbook.close()
    return export_path


def _resolve_export_value(
    field_name: str,
    item: TaskItem,
    task_snapshot: TaskSnapshot,
    review: ReviewRecord | None,
    machine_screening: MachineScreeningRecord | None,
) -> object:
    review_data = _merged_review_data(
        task_snapshot,
        review=review,
        machine_screening=machine_screening,
    )
    if field_name in review_data:
        return review_data[field_name]
    if field_name in item.task_data:
        return item.task_data[field_name]
    return ""


def _merged_review_data(
    task_snapshot: TaskSnapshot,
    *,
    review: ReviewRecord | None,
    machine_screening: MachineScreeningRecord | None,
) -> dict[str, object]:
    merged = dict(review.review_data) if review is not None else {}
    field = machine_screening_field(task_snapshot)
    if field is None or machine_screening is None:
        return merged
    if field.field_id not in merged:
        value = screen_value_for_result(field, machine_screening.result_code)
        if value is not None:
            merged[field.field_id] = value
    remark_field = machine_remark_field(task_snapshot)
    machine_note = str(machine_screening.details.get("machine_note") or "").strip()
    if (
        remark_field is not None
        and machine_note
        and not str(merged.get(remark_field.field_id) or "").strip()
    ):
        merged[remark_field.field_id] = machine_note
    return merged


def _safe_filename(value: str) -> str:
    sanitized = "".join(char if char not in '<>:"/\\|?*' else "_" for char in value).strip()
    return sanitized or "task_export"


def _unique_export_path(export_path: Path) -> Path:
    if not export_path.exists():
        return export_path

    stem = export_path.stem
    suffix = export_path.suffix
    for counter in range(1, 10000):
        candidate = export_path.with_name(f"{stem}_{counter:02d}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Unable to create a unique export path for {export_path}")
