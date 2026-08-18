"""트레이 아이콘 (Windows) — pystray 로 시스템 트레이에 표시한다.

macOS 와 달리 Windows 는 NSApplication 런루프 제약이 없으므로 pystray 를
별도 데몬 스레드에서 실행해도 pywebview 창과 충돌하지 않는다.

풍선 알림(icon.notify)을 core.notify 백엔드로 등록해, 전송 완료/실패 알림을
새 의존성 없이 트레이로 띄운다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from s3manager import settings
from s3manager.core import notify as notify_module

logger = logging.getLogger(__name__)


def create_status_item(
    show_window: Callable[[], None],
    quit_app: Callable[[], None],
) -> list[object]:
    """트레이 아이콘을 만들고 별도 스레드에서 구동한다.

    Returns:
        GC 방지를 위해 호출자가 보관할 객체들(icon, thread).
    """
    import pystray
    from PIL import Image

    icon_path = settings.assets_dir() / "tray.png"
    try:
        image = Image.open(icon_path)
    except Exception:
        # 아이콘이 없어도 트레이는 떠야 한다 — 단색 대체 이미지
        image = Image.new("RGBA", (64, 64), (37, 99, 235, 255))

    menu = pystray.Menu(
        pystray.MenuItem("창 열기", lambda _icon, _item: show_window(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("종료", lambda _icon, _item: quit_app()),
    )

    icon = pystray.Icon("datamanager", image, settings.APP_NAME, menu)

    def _notify(title: str, message: str) -> None:
        try:
            icon.notify(message, title)
        except Exception as exc:
            logger.debug("트레이 알림 실패: %s", exc)

    notify_module.set_backend(_notify)

    thread = threading.Thread(target=icon.run, daemon=True, name="tray")
    thread.start()
    logger.info("트레이 아이콘 생성 완료 (Windows)")
    return [icon, thread]
