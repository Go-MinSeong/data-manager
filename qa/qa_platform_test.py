"""QA: 플랫폼 분기 검증 — 윈도우 포팅이 맥 동작을 깨지 않았는지 맥에서 미리 확인한다.

한계(정직하게): macOS 에서는 WindowsPath 를 인스턴스화할 수 없어 윈도우 경로를
실제로 만들어보는 검증은 불가능하다. 그건 윈도우 PC 에서 확인한다.
여기서는 맥에서 확인 가능한 것만 본다:
  1. macOS 사용자 데이터 경로가 그대로다(바뀌면 기존 자격증명·이력이 끊긴다).
  2. 윈도우 분기가 %APPDATA% 를 쓰도록 작성돼 있다(소스 수준).
  3. 트레이 진입점이 플랫폼별로 분기하고, 구현이 실패해도 앱을 죽이지 않는다.
  4. 알림이 플랫폼별 백엔드로 분기한다(윈도우는 셸이 등록한 트레이 백엔드 사용).
  5. spec 의 hidden import 가 플랫폼별로 올바로 갈린다.
"""
import re
import time
from pathlib import Path
from unittest import mock

from s3manager import settings

ROOT = Path(__file__).resolve().parents[1]


def test_macos_paths_unchanged():
    assert settings.IS_MACOS is True, "이 테스트는 macOS 에서 실행한다"
    expected = Path.home() / "Library" / "Application Support" / "S3Manager"
    assert settings.APP_SUPPORT_DIR == expected, (
        f"macOS 데이터 경로가 바뀌면 기존 프로파일·이력이 끊긴다: {settings.APP_SUPPORT_DIR}"
    )


def test_windows_branch_uses_appdata():
    """윈도우 분기 소스 확인(실제 경로 생성은 윈도우에서 검증)."""
    src = (ROOT / "src" / "s3manager" / "settings.py").read_text(encoding="utf-8")
    win_block = src.split("if IS_WINDOWS:")[1].split("else:")[0]
    assert "APPDATA" in win_block, "윈도우 데이터 경로가 %APPDATA% 를 쓰지 않는다"
    assert "DataManager" in win_block, "윈도우 데이터 폴더명이 없다"


def test_tray_dispatch_and_resilience():
    from s3manager.shell import tray

    with mock.patch("s3manager.shell.tray_macos.create_status_item", return_value=["x"]) as m:
        refs = tray.create_status_item(lambda: None, lambda: None)
        assert m.called and refs == ["x"]

    # 구현이 예외를 던져도 앱은 계속 동작해야 한다(트레이는 보조 진입점)
    with mock.patch("s3manager.shell.tray_macos.create_status_item", side_effect=RuntimeError("boom")):
        assert tray.create_status_item(lambda: None, lambda: None) == []


def test_notify_dispatch():
    from s3manager.core import notify

    got = []
    notify.set_backend(lambda title, body: got.append((title, body)))
    try:
        with mock.patch.object(settings, "IS_MACOS", False):
            notify.notify("제목", "본문", "부제")
            time.sleep(0.3)  # 백엔드는 데몬 스레드에서 호출된다
        assert got and got[0][0] == "제목" and "본문" in got[0][1], got
    finally:
        notify.set_backend(None)

    # 백엔드가 없으면 조용히 무시(예외 없음)
    with mock.patch.object(settings, "IS_MACOS", False):
        notify.notify("제목", "본문")


def test_spec_platform_hidden_imports():
    """spec 의 PLATFORM_HIDDEN 블록만 떼어 두 플랫폼으로 평가한다."""
    src = (ROOT / "packaging" / "s3manager.spec").read_text(encoding="utf-8")
    m = re.search(r"(if IS_WINDOWS:\n\s+PLATFORM_HIDDEN.*?\n)(?=\na = Analysis\()", src, re.S)
    assert m, "spec 에서 PLATFORM_HIDDEN 블록을 찾지 못했다"
    block = m.group(1)

    for is_win, must_have, must_not in (
        (True, "pystray._win32", "pystray._darwin"),
        (False, "pystray._darwin", "pystray._win32"),
    ):
        ns = {"IS_WINDOWS": is_win}
        exec(block, ns)
        hidden = ns["PLATFORM_HIDDEN"]
        assert must_have in hidden, f"IS_WINDOWS={is_win}: {must_have} 누락 ({hidden})"
        assert must_not not in hidden, f"IS_WINDOWS={is_win}: {must_not} 가 잘못 포함됨"

    # 윈도우 빌드에 필요한 백엔드가 모두 있는지
    ns = {"IS_WINDOWS": True}
    exec(block, ns)
    for need in ("webview.platforms.edgechromium", "keyring.backends.Windows"):
        assert need in ns["PLATFORM_HIDDEN"], f"윈도우 hidden import 누락: {need}"


def main():
    for fn in (
        test_macos_paths_unchanged,
        test_windows_branch_uses_appdata,
        test_tray_dispatch_and_resilience,
        test_notify_dispatch,
        test_spec_platform_hidden_imports,
    ):
        fn()
        print(f"  ✓ {fn.__name__}")
    print("\n✅ 플랫폼 분기 검증 통과 (맥 동작 불변 + 분기 구성 정상)")


if __name__ == "__main__":
    main()
