"""앱 환경설정 저장/조회.

숨긴 버킷 목록 등 사용자 UI 설정을 JSON으로 영속화한다.
저장 위치: settings.APP_SUPPORT_DIR / preferences.json (자격증명 등 민감정보는 저장하지 않음).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from s3manager import settings

logger = logging.getLogger(__name__)

_PREFS_PATH = settings.APP_SUPPORT_DIR / "preferences.json"

_DEFAULTS: dict[str, Any] = {
    "hiddenBuckets": [],
}


def load_preferences() -> dict[str, Any]:
    """환경설정을 로드한다. 파일이 없거나 손상되면 기본값을 반환한다."""
    prefs = dict(_DEFAULTS)
    try:
        if _PREFS_PATH.exists():
            data = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                prefs.update(data)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("환경설정 로드 실패(기본값 사용): %s", exc)
    # 타입 보정
    if not isinstance(prefs.get("hiddenBuckets"), list):
        prefs["hiddenBuckets"] = []
    return prefs


def save_preferences(prefs: dict[str, Any]) -> None:
    """환경설정을 디스크에 저장한다."""
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREFS_PATH.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.error("환경설정 저장 실패: %s", exc)
        raise


def get_hidden_buckets() -> list[str]:
    """숨긴 버킷 이름 목록."""
    return list(load_preferences().get("hiddenBuckets", []))


def set_hidden_buckets(names: list[str]) -> list[str]:
    """숨긴 버킷 목록을 저장하고 정규화된 목록을 반환한다."""
    cleaned = sorted({n.strip() for n in names if n and n.strip()})
    prefs = load_preferences()
    prefs["hiddenBuckets"] = cleaned
    save_preferences(prefs)
    return cleaned
