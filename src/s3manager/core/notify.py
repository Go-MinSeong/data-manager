"""잡 완료/실패 알림 — 플랫폼별 best-effort.

- macOS: osascript `display notification` (코드 서명·추가 의존성 불필요)
- Windows: 트레이 아이콘의 풍선 알림(pystray) — 셸이 시작 시 백엔드를 등록한다.
  새 의존성 없이 이미 쓰는 pystray 를 재사용한다.

알림 실패가 잡 흐름에 영향을 주지 않도록 모든 예외를 삼키고, 서브프로세스는
데몬 스레드에서 비차단으로 실행한다.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Callable

from s3manager import settings

logger = logging.getLogger(__name__)

# 플랫폼 셸이 주입하는 알림 백엔드(현재 Windows 트레이용). (title, message) -> None
_backend: Callable[[str, str], None] | None = None


def set_backend(fn: Callable[[str, str], None] | None) -> None:
    """알림 백엔드를 등록한다(Windows 셸이 트레이 아이콘 생성 후 호출)."""
    global _backend
    _backend = fn


def _escape(s: str) -> str:
    """AppleScript 문자열 리터럴용 이스케이프(역슬래시·따옴표)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _notify_macos(title: str, message: str, subtitle: str) -> None:
    osa = shutil.which("osascript")
    if not osa:
        return

    def _run() -> None:
        try:
            script = (
                f'display notification "{_escape(message)}" '
                f'with title "{_escape(title)}"'
            )
            if subtitle:
                script += f' subtitle "{_escape(subtitle)}"'
            subprocess.run([osa, "-e", script], timeout=10, capture_output=True)
        except Exception as exc:
            logger.debug("알림 표시 실패: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


def notify(title: str, message: str, subtitle: str = "") -> None:
    """비차단으로 데스크톱 알림을 띄운다(best-effort, 실패해도 조용히 무시)."""
    try:
        if settings.IS_MACOS:
            _notify_macos(title, message, subtitle)
            return
        if _backend is not None:
            body = f"{subtitle}\n{message}" if subtitle else message
            threading.Thread(
                target=lambda: _backend(title, body), daemon=True  # type: ignore[misc]
            ).start()
    except Exception as exc:
        logger.debug("알림 처리 실패: %s", exc)
