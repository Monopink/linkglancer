from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from machine_screening.models import TikTokVideoStat

_ITEM_LIST_PATH_MARKER = "/api/post/item_list/"
_VIDEO_ID_PATTERN = re.compile(r"/video/(\d+)")
_VIEW_COUNT_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMB]?)\s*$", re.IGNORECASE)


def extract_videos_from_item_list_payload(payload: dict[str, object]) -> list[TikTokVideoStat]:
    item_list = payload.get("itemList")
    if not isinstance(item_list, list):
        return []
    videos: list[TikTokVideoStat] = []
    for item in item_list:
        if not isinstance(item, dict):
            continue
        stats = item.get("stats")
        if not isinstance(stats, dict):
            continue
        play_count = _int_value(stats.get("playCount"))
        if play_count is None:
            continue
        video_id = str(item.get("id") or "").strip()
        if not video_id:
            continue
        videos.append(
            TikTokVideoStat(
                video_id=video_id,
                play_count=play_count,
                is_pinned=bool(item.get("isPinnedItem", False)),
            )
        )
    return videos


def extract_videos_from_item_list_response_body(
    response_url: str,
    body_text: str,
) -> list[TikTokVideoStat]:
    if _ITEM_LIST_PATH_MARKER not in response_url:
        return []
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return extract_videos_from_item_list_payload(payload)


def extract_videos_from_profile_html(html: str) -> list[TikTokVideoStat]:
    parser = _TikTokProfileHtmlParser()
    parser.feed(html)
    return parser.videos


def parse_display_play_count(value: str) -> int | None:
    match = _VIEW_COUNT_PATTERN.match(value)
    if match is None:
        return None
    number = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }.get(suffix)
    if multiplier is None:
        return None
    return int(number * multiplier)


def _int_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class _TikTokProfileHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.videos: list[TikTokVideoStat] = []
        self._current_video_id = ""
        self._current_play_count: int | None = None
        self._current_is_pinned = False
        self._capturing_views = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        href = attr_map.get("href", "")
        video_id_match = _VIDEO_ID_PATTERN.search(href)
        if tag == "a" and video_id_match is not None:
            self._flush_video()
            self._current_video_id = video_id_match.group(1)
            self._current_play_count = None
            self._current_is_pinned = False
            return
        if attr_map.get("data-e2e") == "video-views":
            self._capturing_views = True
            return
        if attr_map.get("data-e2e") == "video-card-badge":
            self._current_is_pinned = True

    def handle_endtag(self, tag: str) -> None:
        if self._capturing_views and tag == "strong":
            self._capturing_views = False
        if tag == "a":
            self._flush_video()

    def handle_data(self, data: str) -> None:
        if not self._capturing_views:
            return
        play_count = parse_display_play_count(data)
        if play_count is not None:
            self._current_play_count = play_count

    def close(self) -> None:
        super().close()
        self._flush_video()

    def _flush_video(self) -> None:
        if not self._current_video_id or self._current_play_count is None:
            self._current_video_id = ""
            self._current_play_count = None
            self._current_is_pinned = False
            return
        self.videos.append(
            TikTokVideoStat(
                video_id=self._current_video_id,
                play_count=self._current_play_count,
                is_pinned=self._current_is_pinned,
            )
        )
        self._current_video_id = ""
        self._current_play_count = None
        self._current_is_pinned = False
