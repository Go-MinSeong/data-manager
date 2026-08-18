"""메뉴바 아이콘(NSStatusItem) — pywebview가 소유한 NSApplication 런루프에 직접 부착.

⚠️ macOS에는 NSApplication 메인 런루프가 하나뿐이다. pystray를 별도 스레드에서
실행하면 pywebview의 webview.start()와 런루프를 두고 충돌해 start()가 즉시 반환된다.
따라서 별도 런루프를 띄우지 않고, pyobjc로 NSStatusItem을 메인 스레드에서 생성해
pywebview의 런루프가 함께 구동하도록 한다.

main.py 에서 show_window / quit_app 콜백을 주입받는다. 메뉴 액션은 AppKit이
메인 스레드에서 호출하므로 콜백 안에서 창 조작이 안전하다.
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
    """메뉴바 NSStatusItem을 생성한다(메인 스레드에서 호출할 것).

    별도의 런루프를 실행하지 않는다 — pywebview의 webview.start()가 런루프를 구동한다.

    Returns:
        GC로 수거되지 않도록 살려둬야 하는 객체들의 리스트
        (status item, target, menu). 호출자가 참조를 보관해야 한다.
    """
    import AppKit
    from Foundation import NSObject

    class _MenuTarget(NSObject):
        """메뉴 항목의 target-action 핸들러."""

        def initWithHandlers_(self, handlers):  # noqa: N802
            self = self.init()
            if self is None:
                return None
            self._handlers = handlers
            return self

        def onOpen_(self, _sender):  # noqa: N802
            try:
                self._handlers["open"]()
            except Exception:
                logger.exception("창 열기 콜백 실패")

        def onQuit_(self, _sender):  # noqa: N802
            try:
                self._handlers["quit"]()
            except Exception:
                logger.exception("종료 콜백 실패")

    # 앱이 메뉴바 액세서리로 동작하도록(독 아이콘 없이도 메뉴/포커스 정상)
    app = AppKit.NSApplication.sharedApplication()

    statusbar = AppKit.NSStatusBar.systemStatusBar()
    status_item = statusbar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)

    # 아이콘 로드 (template 이미지 → 다크/라이트 메뉴바 자동 대응)
    icon_path = settings.assets_dir() / "tray.png"
    image = None
    if icon_path.exists():
        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon_path))
    if image is not None:
        image.setTemplate_(True)
        # 메뉴바에 표시할 높이(pt). 가로는 원본 비율 유지.
        # 너무 크지 않게 약간의 여백을 둬서 옆 아이콘들과 크기를 맞춘다.
        target_h = 16.0
        native = image.size()
        if native.height > 0:
            aspect = native.width / native.height
        else:
            aspect = 1.0
        image.setSize_(AppKit.NSMakeSize(target_h * aspect, target_h))
        status_item.button().setImage_(image)
    else:
        status_item.button().setTitle_("DATA")

    status_item.button().setToolTip_(settings.APP_NAME)

    target = _MenuTarget.alloc().initWithHandlers_({"open": show_window, "quit": quit_app})

    menu = AppKit.NSMenu.alloc().init()

    open_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "창 열기", "onOpen:", ""
    )
    open_item.setTarget_(target)
    menu.addItem_(open_item)

    menu.addItem_(AppKit.NSMenuItem.separatorItem())

    quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "종료", "onQuit:", "q"
    )
    quit_item.setTarget_(target)
    menu.addItem_(quit_item)

    status_item.setMenu_(menu)

    logger.info("메뉴바 아이콘 생성 완료")
    # GC 방지를 위해 참조를 모두 반환 (main.py가 보관)
    return [status_item, target, menu, image]
