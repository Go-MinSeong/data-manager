"""Data Manager 앱 진입점.

실행 순서:
1. FastAPI(uvicorn) 서버를 백그라운드 스레드에서 기동.
2. /api/health 폴링 → 서버 준비 완료 확인.
3. NativeBridge 를 server.app 에 주입.
4. pywebview 창 생성.
5. pystray 트레이를 별도 스레드에서 기동.
6. pywebview.start() 를 메인 스레드에서 실행 (macOS GUI 필수).

macOS 제약:
- Cocoa GUI는 반드시 메인 스레드에서 실행해야 한다.
  → pywebview.start() 는 메인 스레드에서 호출한다.
  → pystray 는 별도 daemon 스레드에서 실행한다.
- 창을 닫아도 앱이 종료되지 않도록 should_close 콜백에서 hide() 처리한다.
"""

from __future__ import annotations

import faulthandler
import logging
import secrets
import signal
import sys
import threading
import time
import urllib.request
import urllib.error

import uvicorn

from s3manager import settings


# 진단 로그·스택 덤프 설정.
#
# ⚠️ Windows 의 창 모드 실행 파일(console=False)은 sys.stderr 가 None 이다.
#    그대로 faulthandler.enable() 을 부르면 RuntimeError 로 앱이 기동조차 못 한다.
#    게다가 stdout/stderr 가 사라져 실패 원인을 볼 방법이 없으므로 파일 로그를 남긴다.
#    (macOS 는 LaunchAgent 가 stderr 를 ~/Library/Logs/DataManager.log 로 보낸다.)
_log_fp = None  # 파일 핸들 전역 유지 — 닫히면 faulthandler 가 쓰지 못한다


def _setup_diagnostics() -> None:
    """faulthandler + (stderr 가 없는 환경에서는) 회전 파일 로그를 설정한다."""
    global _log_fp

    need_file = settings.IS_WINDOWS or sys.stderr is None
    if need_file:
        try:
            log_dir = settings.APP_SUPPORT_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "app.log"

            # 로깅: 회전 파일 핸들러(무한 증가 방지 — 과거 예외 폭주로 로그가 폭증한 적 있음)
            from logging.handlers import RotatingFileHandler

            handler = RotatingFileHandler(
                log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            root = logging.getLogger()
            root.addHandler(handler)
            root.setLevel(logging.WARNING)

            # faulthandler 는 파일 객체(fd)에 직접 쓴다 — 열어둔 채 유지한다.
            _log_fp = open(log_path, "a", encoding="utf-8")
            faulthandler.enable(file=_log_fp)
            return
        except Exception:
            # 파일 로그 설정 실패가 기동을 막아서는 안 된다.
            pass

    try:
        faulthandler.enable()
    except Exception:
        pass


_setup_diagnostics()

# SIGUSR1 → 모든 스레드의 파이썬 스택 덤프(데드락 중에도 동작: C 핸들러가 fd 직접 write).
# 사용: kill -USR1 <pid>. 유닉스 전용 — Windows 에는 없으므로 건너뛴다.
if hasattr(signal, "SIGUSR1"):
    try:
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
    except Exception:
        pass


# ------------------------------------------------------------------ #
#  서버 기동 헬퍼                                                       #
# ------------------------------------------------------------------ #

def _start_server() -> None:
    """uvicorn 서버를 현재 스레드에서 블로킹 실행한다."""
    config = uvicorn.Config(
        app="s3manager.server.app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level="warning",
        # 단일 워커 — 로컬 전용
        workers=1,
    )
    server = uvicorn.Server(config)
    server.run()


def _wait_for_server(timeout: float = 30.0, interval: float = 0.2) -> bool:
    """서버가 /api/health 에 응답할 때까지 폴링 대기.

    Returns:
        True: 정상 응답, False: 타임아웃
    """
    health_url = f"{settings.BASE_URL}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# ------------------------------------------------------------------ #
#  창 드래그 — 네이티브 위임                                            #
# ------------------------------------------------------------------ #

def _install_native_drag() -> None:
    """pywebview의 JS 좌표계산 드래그를 macOS 네이티브 드래그로 교체한다(macOS 전용).

    기본 구현은 mousemove마다 JS→브릿지→setFrameTopLeftPoint_ 로 창을 옮기는데,
    좌표 뒤집기가 창 생성 당시의 단일 스크린 기준이라 다른 모니터(원점·높이 상이)로
    넘어가면 창이 커서를 못 따라오고 끊긴다. AppKit의 performWindowDragWithEvent: 는
    멀티모니터·배율 차이를 커널이 처리하고 채널 왕복이 없어 부드럽다.

    pywebview의 드래그 영역 감지(.pywebview-drag-region + DIRECT_TARGET_ONLY,
    버튼 클릭 제외)는 그대로 두고 실제 이동만 위임한다. 인스턴스 move() 는 드래그 시
    AppHelper.callAfter 로 메인 스레드에서 호출되므로 AppKit 직접 호출이 안전하다.
    """
    if not settings.IS_MACOS:
        return
    try:
        import AppKit
        from webview.platforms import cocoa

        _LEFT_DOWN = getattr(AppKit, "NSEventTypeLeftMouseDown", 1)
        _LEFT_DRAG = getattr(AppKit, "NSEventTypeLeftMouseDragged", 6)
        _dragging = {"on": False}

        def _native_move(self, x, y):  # noqa: ANN001
            # 드래그 진행 중(모달) 재진입, 드래그 종료 후 큐에 남은 중복 호출은 무시
            if _dragging["on"]:
                return
            win = getattr(self, "window", None)
            ev = AppKit.NSApplication.sharedApplication().currentEvent()
            # 마우스 드래그 이벤트일 때만 네이티브 드래그 시작(버튼 뗀 뒤 stray 호출 차단)
            if win is None or ev is None or ev.type() not in (_LEFT_DOWN, _LEFT_DRAG):
                return
            _dragging["on"] = True
            try:
                win.performWindowDragWithEvent_(ev)  # mouseUp까지 모달, 네이티브 이동
            finally:
                _dragging["on"] = False

        cocoa.BrowserView.move = _native_move
    except Exception:
        logging.getLogger(__name__).debug("네이티브 드래그 설치 실패", exc_info=True)


# ------------------------------------------------------------------ #
#  메인 진입점                                                          #
# ------------------------------------------------------------------ #

def main() -> None:
    """앱 메인 함수 — pyproject.toml scripts 진입점."""

    # 1. FastAPI 서버를 백그라운드 스레드로 기동
    server_thread = threading.Thread(target=_start_server, daemon=True, name="uvicorn")
    server_thread.start()

    # 2. 서버 준비 완료까지 대기
    print(f"[Data Manager] 서버 기동 대기 중... ({settings.BASE_URL})")
    if not _wait_for_server():
        print("[Data Manager] 오류: 서버 기동 타임아웃. 앱을 종료합니다.")
        sys.exit(1)
    print("[Data Manager] 서버 준비 완료.")

    # 3. NativeBridge 주입 + 로컬 접근 토큰 발급/등록
    from s3manager.shell.bridge import NativeBridge
    from s3manager.server.app import set_auth_token, set_native_bridge  # type: ignore[import]

    bridge = NativeBridge()
    set_native_bridge(bridge)

    # 실행마다 무작위 토큰을 발급. 이 토큰을 모르는 다른 프로세스/브라우저는 API 접근 불가.
    # 토큰은 창 URL(?t=)로만 전달되며, 서버가 서빙하는 HTML에는 포함되지 않는다.
    auth_token = secrets.token_urlsafe(32)
    set_auth_token(auth_token)

    # 4. pywebview 창 생성 (아직 start 전)
    import webview

    # 드래그 영역: 클래스(.pywebview-drag-region)를 "직접" 클릭할 때만 창 이동.
    # 헤더의 빈 영역을 끌면 창이 움직이고, 그 안의 버튼 클릭은 드래그로 새지 않는다.
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

    _install_native_drag()

    window = webview.create_window(
        title=settings.APP_NAME,
        url=f"{settings.BASE_URL}/?t={auth_token}",
        width=1100,
        height=760,
        min_size=(800, 600),
        # 창 닫기 버튼을 눌러도 앱이 종료되지 않도록 — hide 처리
        # (pywebview 5.x: on_closed 는 이미 닫힌 후, hidden 을 지원하면 사용)
    )

    # ---------------------------------------------------------------- #
    #  창 상태 제어 헬퍼                                                  #
    # ---------------------------------------------------------------- #

    _window_visible = [True]  # mutable 참조 (closure 용)

    def show_window() -> None:
        """메뉴바에서 창 보이기 + 앞으로 가져오기.

        앱이 Accessory(Dock 미표시) 모드라 창을 띄워도 자동으로 활성화되지 않는다.
        따라서 show() 후 NSApp을 명시적으로 activate 해야 창이 앞으로 온다.
        (메뉴 액션은 메인 스레드에서 호출되므로 AppKit 직접 호출이 안전하다.)
        """
        try:
            window.show()
            _window_visible[0] = True
        except Exception:
            pass
        if settings.IS_MACOS:
            try:
                import AppKit

                AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass
        else:
            # Windows: 창을 앞으로 (pywebview 가 지원하면 사용, 실패해도 show 로 충분)
            try:
                window.restore()
            except Exception:
                pass

    def on_window_closed() -> None:
        """창 닫기 버튼 → 실제로 닫지 않고 숨긴다."""
        _window_visible[0] = False
        try:
            window.hide()
        except Exception:
            pass

    # pywebview 5.x closing 이벤트: False 반환 → 닫기 취소
    def on_closing() -> bool:
        """창 닫기 시도 시 호출.

        빨간 버튼이면 숨기고(False), **진짜 종료 요청이면 허용한다(True).**
        pywebview의 applicationShouldTerminate_ 는 모든 창의 closing 결과를 AND 해서
        종료 여부를 정하므로, 늘 False를 주면 로그아웃·시스템 종료가 차단된다
        ("앱이 종료되지 않아 컴퓨터를 끌 수 없음").
        `_quit_requested`는 아래에서 정의되지만 클로저는 호출 시점에 해석되므로 괜찮다.
        """
        if _quit_requested.is_set():
            return True
        on_window_closed()
        return False  # False = 닫기 취소

    # ---------------------------------------------------------------- #
    #  앱 종료 처리                                                       #
    # ---------------------------------------------------------------- #

    _quit_requested = threading.Event()
    # 트레이 참조는 아래에서 채워지지만, Windows 는 트레이가 별도 스레드로 먼저 뜨므로
    # quit_app 이 그 전에 불릴 여지가 있다. 미리 비워 두어 NameError 를 막는다.
    _tray_refs: list[object] = []

    def quit_app() -> None:
        """메뉴바/트레이 "종료" 클릭 → 서버·창 정리하고 종료."""
        _quit_requested.set()
        # Windows: pystray 아이콘을 명시적으로 정리한다. 안 그러면 프로세스가 끝나도
        # 트레이에 아이콘 잔상이 남아(마우스를 올려야 사라짐) 종료된 걸로 안 보인다.
        if settings.IS_WINDOWS:
            for ref in _tray_refs:
                stop = getattr(ref, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
        # pywebview 종료 → webview.start() 반환 → 프로세스 종료
        try:
            webview.windows[0].destroy()
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  5. 메뉴바 아이콘 — pywebview와 동일한 NSApp에 부착 (별도 런루프 없음)  #
    # ---------------------------------------------------------------- #
    # macOS는 메인 NSApplication 런루프가 하나뿐이므로, pystray를 별도 스레드로
    # 돌리면 webview.start()와 충돌해 즉시 반환된다. 따라서 pyobjc로 NSStatusItem을
    # 메인 스레드에서 만들어 pywebview 런루프가 함께 구동하게 한다.
    from s3manager.shell.tray import create_status_item

    # GC 방지: 메뉴바/트레이 객체 참조를 살려둔다(위에서 만든 리스트를 그대로 채운다)
    _tray_refs.extend(create_status_item(show_window=show_window, quit_app=quit_app))

    # ---------------------------------------------------------------- #
    #  6. pywebview 메인 루프 (메인 스레드 — macOS 필수)                  #
    # ---------------------------------------------------------------- #

    # closing 이벤트 연결 (pywebview 5.x API)
    window.events.closing += on_closing

    _dock_refs: list[object] = []

    def _setup_dock_reopen() -> None:
        """Dock 아이콘을 표시하고, 클릭(리오픈) 시 숨겨진 창을 다시 띄운다.

        앱은 Dock 아이콘과 메뉴바 아이콘을 함께 쓴다(ActivationPolicy=Regular,
        pywebview가 import 시 설정함). 창을 닫으면 숨기므로, Dock 아이콘을 누르면
        창이 다시 보이도록 reopen 델리게이트를 단다. pywebview의 AppDelegate를 상속해
        종료 처리 등 기존 동작은 그대로 유지한다.
        """
        if not settings.IS_MACOS:
            return
        try:
            import AppKit
            from webview.platforms.cocoa import BrowserView

            class _ReopenDelegate(BrowserView.AppDelegate):
                def applicationShouldTerminate_(self, app):  # noqa: N802
                    """Cmd+Q·로그아웃·시스템 종료 — 항상 종료를 허용한다.

                    상위 구현(super)을 부르지 않는다. pywebview의 구현은 모든 창의
                    closing 결과를 AND 하는 것뿐이고, 그 판단은 우리가 이미 내렸다.
                    게다가 PyObjC에서 파이썬 기본 super()는 ObjC 메서드로 제대로
                    디스패치되지 않는다 (ObjCSuperWarning) — 그래서 종료가 거부됐다.

                    1 = NSTerminateNow. 종료를 막지 않는 것이 이 앱의 올바른 동작이다:
                    막으면 사용자가 컴퓨터를 끌 수 없다.
                    """
                    _quit_requested.set()
                    return 1

                def applicationShouldHandleReopen_hasVisibleWindows_(  # noqa: N802
                    self, app, flag
                ):
                    try:
                        show_window()
                    except Exception:
                        pass
                    return True

            def _set() -> None:
                delegate = _ReopenDelegate.alloc().init()
                _dock_refs.append(delegate)  # GC 방지
                AppKit.NSApplication.sharedApplication().setDelegate_(delegate)

            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_set)
        except Exception:
            logging.getLogger(__name__).debug("Dock reopen 설정 실패", exc_info=True)

    def _unify_titlebar() -> None:
        """타이틀바를 앱 UI와 하나로 보이게 한다(창 표시 후 메인 스레드에서 적용).

        제목 막대를 투명화·텍스트 숨김하고 콘텐츠 뷰를 창 최상단까지 확장한다.
        pywebview가 타이틀바에 칠한 배경색을 투명으로 되돌려 앱의 어두운 헤더가
        그대로 비치게 한다. macOS 신호등(닫기·최소화·확대) 버튼은 그대로 유지된다.
        """
        if not settings.IS_MACOS:
            return  # Windows 는 네이티브 타이틀바를 그대로 사용한다
        try:
            import AppKit

            ns = getattr(window, "native", None)
            if ns is None:
                return

            def _apply() -> None:
                ns.setTitlebarAppearsTransparent_(True)
                ns.setTitleVisibility_(1)  # NSWindowTitleHidden
                # NSFullSizeContentViewWindowMask(1<<15) — 콘텐츠를 타이틀바 아래까지 채움
                ns.setStyleMask_(ns.styleMask() | (1 << 15))
                # pywebview가 타이틀바에 칠한 회색(windowBackgroundColor)을 투명으로 되돌림
                try:
                    titlebar = ns.contentView().superview().subviews().lastObject()
                    titlebar.setBackgroundColor_(AppKit.NSColor.clearColor())
                except Exception:
                    pass
                ns.displayIfNeeded()

            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_apply)
        except Exception:
            pass

    def _register_file_drop() -> None:
        """Finder에서 끌어온 파일의 절대경로를 프론트엔드로 전달한다.

        WKWebView의 JS는 드롭된 파일의 절대경로를 노출하지 않는다. pywebview는
        네이티브 드롭에서 경로를 모아 Python DOM 이벤트의 pywebviewFullPath로 준다.
        이를 받아 window.__onFilesDropped(paths)로 넘기면 React가 업로드 목록에 추가한다.
        """
        try:
            import json as _json
            from webview.dom import DOMEventHandler

            def _on_drop(event) -> None:
                try:
                    # 드롭이 전달되는 즉시 로딩 표시(경로 추출·프론트 렌더 동안).
                    window.evaluate_js(
                        "window.__onFilesDropStart && window.__onFilesDropStart()"
                    )
                    files = (event or {}).get("dataTransfer", {}).get("files", []) or []
                    paths = [f.get("pywebviewFullPath") for f in files]
                    paths = [p for p in paths if p]
                    # 빈 목록도 전달해 로딩 표시를 반드시 해제한다.
                    window.evaluate_js(
                        "window.__onFilesDropped && window.__onFilesDropped("
                        + _json.dumps(paths)
                        + ")"
                    )
                except Exception:
                    logging.getLogger(__name__).debug("드롭 처리 실패", exc_info=True)

            def _noop(_e) -> None:
                return None

            doc = window.dom.document
            doc.events.dragenter += DOMEventHandler(_noop, prevent_default=True)
            doc.events.dragover += DOMEventHandler(_noop, prevent_default=True)
            doc.events.drop += DOMEventHandler(_on_drop, prevent_default=True)
        except Exception:
            logging.getLogger(__name__).debug("파일 드롭 등록 실패", exc_info=True)

    def _on_start() -> None:
        """런루프 시작 후 호출 — Dock 아이콘 리오픈 핸들러 설치."""
        _setup_dock_reopen()

    # 창이 표시된 뒤에야 native(NSWindow)가 준비되므로 shown 이벤트에서 타이틀바를 통합한다.
    window.events.shown += _unify_titlebar
    # DOM 로드 후 파일 드래그-드롭 핸들러 등록
    window.events.loaded += _register_file_drop

    # func은 런루프 시작 후 호출됨
    webview.start(_on_start)  # 메인 NSApp 런루프 구동 (메뉴바 아이콘도 함께 동작)

    # 참조 유지 (린터의 미사용 변수 경고 방지 겸)
    del _tray_refs

    # webview.start() 가 반환된 후 (quit_app 에서 destroy 호출됨)
    print("[Data Manager] 앱 종료.")
    sys.exit(0)


if __name__ == "__main__":
    main()
