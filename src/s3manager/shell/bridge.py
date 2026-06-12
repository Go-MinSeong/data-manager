"""NativeBridge — pywebview를 통한 네이티브 OS 다이얼로그 및 Finder 연동.

API_CONTRACT.md §2 "Native bridge 협약" 구현.
pick_folder / pick_files 는 pywebview GUI 스레드에서 실행해야 안전하다.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # 타입 힌트 전용 임포트


class NativeBridge:
    """네이티브 OS 기능 브릿지.

    server.app.set_native_bridge(bridge) 로 주입된 뒤
    /api/pick-folder, /api/pick-files, /api/reveal 엔드포인트에서 호출된다.
    """

    # ------------------------------------------------------------------ #
    #  폴더 선택                                                           #
    # ------------------------------------------------------------------ #

    def pick_folder(self) -> str | None:
        """네이티브 폴더 선택 다이얼로그.

        Returns:
            선택된 폴더의 절대 경로, 취소 시 None.
        """
        try:
            import webview  # pywebview

            windows = webview.windows
            if not windows:
                return None

            result = windows[0].create_file_dialog(
                webview.FOLDER_DIALOG,
                allow_multiple=False,
            )
            if result and len(result) > 0:
                return result[0]
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  파일 선택                                                           #
    # ------------------------------------------------------------------ #

    def pick_files(self) -> list[str]:
        """네이티브 파일 선택 다이얼로그 (복수 선택 허용).

        Returns:
            선택된 파일 경로 목록, 취소 시 빈 리스트.
        """
        try:
            import webview  # pywebview

            windows = webview.windows
            if not windows:
                return []

            result = windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
            )
            if result:
                return list(result)
            return []
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    #  Finder 열기                                                         #
    # ------------------------------------------------------------------ #

    def reveal(self, path: str) -> None:
        """Finder에서 지정 경로를 선택 상태로 열기.

        macOS: open -R <path>  (파일을 Finder에서 하이라이트)
        타 플랫폼: 폴더 열기 fallback.
        """
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    ["open", "-R", path],
                    check=False,
                    timeout=10,
                )
            elif sys.platform == "win32":
                # Windows: explorer /select,<path>
                subprocess.run(
                    ["explorer", f"/select,{path}"],
                    check=False,
                    timeout=10,
                )
            else:
                # Linux: xdg-open 폴더
                import os
                folder = path if os.path.isdir(path) else os.path.dirname(path)
                subprocess.run(
                    ["xdg-open", folder],
                    check=False,
                    timeout=10,
                )
        except Exception:
            pass  # reveal 실패는 조용히 무시
