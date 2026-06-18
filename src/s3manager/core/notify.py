"""macOS 알림 — 잡 완료/실패를 알림 센터로 푸시(best-effort).

osascript의 `display notification`을 사용한다: 코드 서명·entitlement 없이도 동작하고
별도 의존성이 필요 없다. 알림 표시 실패가 잡 흐름에 영향을 주지 않도록 모든 예외를
삼키고, 서브프로세스는 데몬 스레드에서 비차단으로 실행한다.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    """AppleScript 문자열 리터럴용 이스케이프(역슬래시·따옴표)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, subtitle: str = "") -> None:
    """비차단으로 macOS 알림을 띄운다(best-effort)."""
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
