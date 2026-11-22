from __future__ import annotations

from statistics import median

from link_glancer.tasks.models import MachineScreeningConfig
from machine_screening.models import MachineScreeningEvaluation, TikTokVideoStat


def evaluate_tiktok_videos(
    *,
    handle: str,
    config: MachineScreeningConfig,
    videos: list[TikTokVideoStat],
) -> MachineScreeningEvaluation:
    non_pinned_videos = [video for video in videos if not video.is_pinned]
    excluded_pinned_count = len(videos) - len(non_pinned_videos)
    target_videos = non_pinned_videos[: config.top_video_count]
    play_counts = [video.play_count for video in target_videos]
    if not play_counts:
        details = {
            "handle": handle,
            "metric_type": config.metric_type,
            "top_video_count": config.top_video_count,
            "threshold": config.play_count_threshold,
            "used_video_count": 0,
            "excluded_pinned_count": excluded_pinned_count,
            "play_counts": [],
            "computed_value": None,
        }
        return MachineScreeningEvaluation(
            result_code="screen_unresolved",
            metric_type=config.metric_type,
            threshold=config.play_count_threshold,
            top_video_count=config.top_video_count,
            used_video_count=0,
            excluded_pinned_count=excluded_pinned_count,
            play_counts=[],
            computed_value=None,
            details=details,
        )

    computed_value = _compute_metric(config.metric_type, play_counts)
    passed = computed_value >= config.play_count_threshold
    details = {
        "handle": handle,
        "metric_type": config.metric_type,
        "top_video_count": config.top_video_count,
        "threshold": config.play_count_threshold,
        "used_video_count": len(play_counts),
        "excluded_pinned_count": excluded_pinned_count,
        "play_counts": play_counts,
        "computed_value": computed_value,
    }
    return MachineScreeningEvaluation(
        result_code="screen_passed" if passed else "screen_failed",
        metric_type=config.metric_type,
        threshold=config.play_count_threshold,
        top_video_count=config.top_video_count,
        used_video_count=len(play_counts),
        excluded_pinned_count=excluded_pinned_count,
        play_counts=play_counts,
        computed_value=computed_value,
        details=details,
    )


def build_machine_screening_note(evaluation: MachineScreeningEvaluation) -> str:
    handle = str(evaluation.details.get("handle") or "该达人").strip() or "该达人"
    if not handle.startswith("@") and handle != "该达人":
        handle = f"@{handle}"
    metric_label = _metric_label(evaluation.metric_type)
    if evaluation.result_code == "screen_unresolved":
        return f"{handle} 自动初筛未完成：无可用的非置顶视频。"
    operator = ">=" if evaluation.result_code == "screen_passed" else "<"
    status_text = "通过" if evaluation.result_code == "screen_passed" else "不通过"
    computed_text = _format_number(evaluation.computed_value)
    return (
        f"{handle} 前{evaluation.top_video_count}个非置顶视频播放量{metric_label} "
        f"{computed_text} {operator} {evaluation.threshold}，自动初筛{status_text}。"
    )


def _compute_metric(metric_type: str, play_counts: list[int]) -> float | int:
    if metric_type == "sum":
        return sum(play_counts)
    if metric_type == "median":
        return float(median(play_counts))
    return sum(play_counts) / len(play_counts)


def _metric_label(metric_type: str) -> str:
    labels = {
        "sum": "总和",
        "avg": "平均值",
        "median": "中位数",
    }
    return labels.get(metric_type, "平均值")


def _format_number(value: float | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)
