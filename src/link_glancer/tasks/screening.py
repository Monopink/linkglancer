from __future__ import annotations

from link_glancer.tasks.models import (
    MachineScreeningResultCode,
    ReviewField,
    TaskRangeScope,
    TaskRangeSelection,
    TaskSnapshot,
)

SCREEN_PASSED = "screen_passed"
SCREEN_FAILED = "screen_failed"
SCREEN_UNRESOLVED = "screen_unresolved"
MACHINE_SCREENING_FIELD_ID = "__machine_screening__"
MACHINE_SCREENING_FIELD_LABEL = "自动初筛结果"


def build_machine_screening_field(
    *,
    field_id: str = MACHINE_SCREENING_FIELD_ID,
    label: str = MACHINE_SCREENING_FIELD_LABEL,
    pass_value: str = "通过",
    fail_value: str = "不通过",
) -> ReviewField:
    return ReviewField(
        field_id=field_id,
        label=label,
        field_type="screen",
        required=False,
        options=[],
        screen_pass_value=pass_value,
        screen_fail_value=fail_value,
        source="machine",
    )


def is_machine_screening_field(field: ReviewField) -> bool:
    return field.field_type == "screen" and field.source == "machine"


def ensure_machine_screening_field(review_fields: list[ReviewField]) -> list[ReviewField]:
    normalized_fields = [field for field in review_fields if not is_machine_screening_field(field)]
    machine_field = next(
        (field for field in review_fields if is_machine_screening_field(field)),
        None,
    )
    normalized_fields.append(
        machine_field if machine_field is not None else build_machine_screening_field()
    )
    return normalized_fields


def machine_screening_field(task_snapshot: TaskSnapshot) -> ReviewField | None:
    return next(
        (field for field in task_snapshot.review_fields if is_machine_screening_field(field)),
        None,
    )


def normalize_machine_screening_result_code(
    value: object,
) -> MachineScreeningResultCode | None:
    if value in {SCREEN_PASSED, SCREEN_FAILED, SCREEN_UNRESOLVED}:
        return value  # type: ignore[return-value]
    return None


def screen_value_for_result(
    field: ReviewField,
    result_code: MachineScreeningResultCode | None,
) -> str | None:
    if result_code == SCREEN_PASSED:
        return field.screen_pass_value
    if result_code == SCREEN_FAILED:
        return field.screen_fail_value
    return None


def screening_fields(task_snapshot: TaskSnapshot) -> list[ReviewField]:
    enabled_ids = set(task_snapshot.enabled_review_field_ids or [])
    return [
        field
        for field in task_snapshot.review_fields
        if field.field_type == "screen" and (not enabled_ids or field.field_id in enabled_ids)
    ]


def normalize_screen_value(field: ReviewField, value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text == field.screen_pass_value:
        return SCREEN_PASSED
    if text == field.screen_fail_value:
        return SCREEN_FAILED
    return None


def machine_screening_summary(task_snapshot: TaskSnapshot, review_data: dict[str, object]) -> str:
    field = machine_screening_field(task_snapshot)
    if field is None:
        return SCREEN_UNRESOLVED
    normalized = normalize_screen_value(field, review_data.get(field.field_id))
    return normalized or SCREEN_UNRESOLVED


def screening_summary(task_snapshot: TaskSnapshot, review_data: dict[str, object]) -> str:
    saw_pass = False
    for field in screening_fields(task_snapshot):
        normalized = normalize_screen_value(field, review_data.get(field.field_id))
        if normalized == SCREEN_FAILED:
            return SCREEN_FAILED
        if normalized == SCREEN_PASSED:
            saw_pass = True
    if saw_pass:
        return SCREEN_PASSED
    return SCREEN_UNRESOLVED


def matches_screening_scope(
    task_snapshot: TaskSnapshot,
    review_data: dict[str, object],
    scope: TaskRangeSelection,
) -> bool:
    if not scope:
        return True
    return screening_summary(task_snapshot, review_data) in scope


def matches_machine_screening_scope(
    task_snapshot: TaskSnapshot,
    review_data: dict[str, object],
    scope: TaskRangeSelection,
) -> bool:
    if not scope:
        return True
    return machine_screening_summary(task_snapshot, review_data) in scope


def screening_scope_label(scope: TaskRangeScope) -> str:
    labels: dict[TaskRangeScope, str] = {
        "screen_passed": "整体通过",
        "screen_failed": "整体不通过",
        "screen_unresolved": "未筛选",
    }
    return labels[scope]


def screening_scope_labels(scopes: TaskRangeSelection) -> str:
    normalized = normalize_task_range_selection(scopes)
    if len(normalized) == 3:
        return "全部"
    return "、".join(screening_scope_label(scope) for scope in normalized)


def normalize_task_range_selection(value: object) -> TaskRangeSelection:
    valid_scopes: tuple[TaskRangeScope, ...] = (
        "screen_passed",
        "screen_failed",
        "screen_unresolved",
    )
    if isinstance(value, str):
        if value == "all":
            return list(valid_scopes)
        if value in valid_scopes:
            return [value]
        return list(valid_scopes)
    if not isinstance(value, list):
        return list(valid_scopes)
    normalized: TaskRangeSelection = []
    for item in value:
        if item in valid_scopes and item not in normalized:
            normalized.append(item)
    return normalized or list(valid_scopes)
