"""아이콘 생성 스크립트 — PIL로 '구름 + S3' 트레이/앱 아이콘을 생성한다.

실행: uv run python assets/generate_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ASSETS = Path(__file__).parent

CLOUD_COLOR = (52, 120, 246, 255)  # 파란색
TEXT_COLOR = (255, 255, 255, 255)  # 흰색


def _bold_font(px: int) -> ImageFont.FreeTypeFont:
    """굵은 시스템 폰트를 로드한다(가능한 후보 순서대로)."""
    candidates = [
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
        ("/System/Library/Fonts/Helvetica.ttc", 1),
        ("/Library/Fonts/Arial Bold.ttf", 0),
        ("/System/Library/Fonts/SFNS.ttf", 0),
    ]
    for path, idx in candidates:
        try:
            return ImageFont.truetype(path, px, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_font(d: ImageDraw.ImageDraw, text: str, max_w: float, max_h: float, start_px: int):
    """text가 (max_w, max_h) 안에 들어가는 가장 큰 굵은 폰트를 반환한다."""
    px = start_px
    while px > 4:
        font = _bold_font(px)
        bbox = d.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w and (bbox[3] - bbox[1]) <= max_h:
            return font
        px -= 1
    return _bold_font(4)


def draw_cloud_s3(size: int, cutout: bool = False, text: str = "S3") -> Image.Image:
    """구름 모양 + 글자 아이콘을 그린다.

    Args:
        size: 정사각형 픽셀 크기
        cutout: True면 글자를 투명하게 도려낸다(메뉴바 template용 단색 실루엣).
                False면 흰색 글자를 구름 위에 그린다(컬러 앱 아이콘).
        text: 구름 위에 표시할 글자 (예: "S3", "DATA").
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    def ellipse(cx: float, cy: float, r: float) -> None:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CLOUD_COLOR)

    # 납작하고 넓은 구름 (높이 낮춤 — 깔끔한 형태, 작은 크기에서도 글자 잘 보이게)
    # 윗면 봉우리(원들) — 봉우리를 낮게
    ellipse(s * 0.28, s * 0.53, s * 0.13)
    ellipse(s * 0.44, s * 0.45, s * 0.165)
    ellipse(s * 0.60, s * 0.46, s * 0.155)
    ellipse(s * 0.74, s * 0.53, s * 0.13)
    # 몸통(둥근 사각형) — 글자가 들어갈 넓은 영역
    d.rounded_rectangle(
        [s * 0.06, s * 0.47, s * 0.94, s * 0.82],
        radius=s * 0.17,
        fill=CLOUD_COLOR,
    )

    # 글자 — 구름 몸통 폭(약 0.82s)에 맞춰 자동 크기 조정, 세로 ~0.625에 배치
    font = _fit_font(d, text, max_w=s * 0.78, max_h=s * 0.30, start_px=int(s * 0.46))
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = s * 0.5 - tw / 2 - bbox[0]
    ty = s * 0.625 - th / 2 - bbox[1]

    if cutout:
        # template(메뉴바)용: 텍스트 영역의 알파를 0으로 도려낸다
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).text((tx, ty), text, font=font, fill=255)
        r, g, b, a = img.split()
        a = ImageChops.subtract(a, mask)
        img = Image.merge("RGBA", (r, g, b, a))
    else:
        d.text((tx, ty), text, font=font, fill=TEXT_COLOR)

    return img


TRAY_TEXT = "DATA"  # 메뉴바 아이콘 글자
APP_TEXT = "DATA"   # 앱(dock/.app) 아이콘 글자


def main() -> None:
    # 트레이용 PNG (메뉴바 template — 단색 실루엣 + 글자 도려내기)
    for sz in [16, 22, 32, 44, 64, 128, 256, 512]:
        draw_cloud_s3(sz, cutout=True, text=TRAY_TEXT).save(str(ASSETS / f"tray_{sz}.png"))
        print(f"  생성: tray_{sz}.png")

    # 트레이 메인 아이콘 — 고해상도로 그린 뒤 구름 경계에 맞춰 크롭(여백 제거).
    # 정사각 캔버스의 위아래 빈 여백 때문에 메뉴바에서 작게 보이던 문제를 해결.
    # 크롭으로 가로로 넓은(납작) 이미지가 되고, tray.py가 높이에 맞춰 키워 표시한다.
    tray_hi = draw_cloud_s3(176, cutout=True, text=TRAY_TEXT)
    bbox = tray_hi.getbbox()  # 불투명(구름) 영역의 경계
    if bbox:
        pad = 6
        left = max(0, bbox[0] - pad)
        top = max(0, bbox[1] - pad)
        right = min(tray_hi.width, bbox[2] + pad)
        bottom = min(tray_hi.height, bbox[3] + pad)
        tray_hi = tray_hi.crop((left, top, right, bottom))
    tray_hi.save(str(ASSETS / "tray.png"))
    print(f"  생성: tray.png (구름+{TRAY_TEXT}, template, 크롭 {tray_hi.size})")

    # 앱 아이콘 (512, 컬러 — 파란 구름 + 흰 글자)
    app_img = draw_cloud_s3(512, cutout=False, text=APP_TEXT)
    app_img.save(str(ASSETS / "app_icon.png"))
    print(f"  생성: app_icon.png (구름+{APP_TEXT}, 컬러)")

    # .icns 생성
    try:
        app_img.save(str(ASSETS / "app_icon.icns"), format="ICNS")
        print("  생성: app_icon.icns")
    except Exception as e:
        print(f"  경고: .icns 직접 생성 실패 ({e}) — build.sh에서 iconutil 사용")

    print("아이콘 생성 완료.")


if __name__ == "__main__":
    main()
