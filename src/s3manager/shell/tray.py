"""트레이/메뉴바 아이콘 — 플랫폼 구현으로 분기한다.

- macOS: NSStatusItem 을 pywebview 의 NSApplication 런루프에 직접 부착(tray_macos)
- Windows: pystray 를 별도 스레드에서 구동(tray_windows)

두 구현 모두 create_status_item(show_window, quit_app) -> list[object] 계약을 지킨다
(반환 리스트는 GC 방지용 참조이며 호출자가 보관한다).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from s3manager import settings

logger = logging.getLogger(__name__)


def create_status_item(
    show_window: Callable[[], None],
    quit_app: Callable[[], None],
) -> list[object]:
    """현재 플랫폼의 트레이 아이콘을 생성한다. 실패해도 앱은 계속 동작한다."""
    try:
        if settings.IS_MACOS:
            from s3manager.shell import tray_macos

            return tray_macos.create_status_item(show_window, quit_app)
        if settings.IS_WINDOWS:
            from s3manager.shell import tray_windows

            return tray_windows.create_status_item(show_window, quit_app)
    except Exception:
        # 트레이는 보조 진입점 — 실패해도 창(Dock/작업표시줄)으로 쓸 수 있어야 한다.
        logger.exception("트레이 아이콘 생성 실패 — 창으로만 동작합니다")
    return []
