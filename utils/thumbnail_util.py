"""게시판 목록 카드에 걸리는 썸네일을 만든다.

게시물은 이미지를 만들지 않으므로 날짜와 무관한 고정 이미지를 한 장 둔다.
한 번 만들어 img/thumbnail.png 로 커밋해 두면 이후 실행에서는 그 파일을 쓴다.

색은 mqway.com tailwind.config 값을 그대로 쓴다. 글자는 맑은 고딕으로 굽는다.
서버에 한글 폰트가 없어도 되도록 이미지로 미리 만들어 두는 것이다.

  python main.py --thumbnail
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from utils.config_util import ROOT
from utils.logger_util import LoggerUtil

THUMBNAIL_PATH = ROOT / "img" / "thumbnail.png"

# 게시판 카드 비율에 맞춘 크기. ApiUtil 이 800px 로 줄이므로 그 이하로 만든다.
WIDTH, HEIGHT = 800, 420

# mqway.com tailwind.config
INK = (45, 48, 71)         # #2D3047
ACCENT = (255, 77, 77)     # #FF4D4D
SURFACE = (248, 249, 250)  # #F8F9FA
MUTED = (107, 114, 128)    # #6B7280

FONT_BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")
FONT_REG = Path("C:/Windows/Fonts/malgun.ttf")


class ThumbnailUtil:
    def __init__(self):
        self.logger = LoggerUtil().get_logger()

    @staticmethod
    def _font(path: Path, size: int):
        if path.exists():
            return ImageFont.truetype(str(path), size)
        return ImageFont.load_default()

    def build(self, out: Path = THUMBNAIL_PATH) -> Path:
        img = Image.new("RGB", (WIDTH, HEIGHT), SURFACE)
        d = ImageDraw.Draw(img)

        # 왼쪽 액센트 띠
        d.rectangle([0, 0, 10, HEIGHT], fill=ACCENT)

        d.text((56, 92), "미국 유동성 지표", font=self._font(FONT_BOLD, 58), fill=INK)
        d.text((56, 172), "주간 브리핑", font=self._font(FONT_BOLD, 58), fill=INK)

        d.line([(56, 268), (176, 268)], fill=ACCENT, width=4)

        d.text((56, 296), "연준 대차대조표 / 지급준비금 / 순유동성",
               font=self._font(FONT_REG, 24), fill=MUTED)
        d.text((56, 334), "출처 FRED", font=self._font(FONT_REG, 22), fill=MUTED)

        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, format="PNG", optimize=True)
        self.logger.info(
            f"썸네일 생성: {out}  ({out.stat().st_size / 1024:.1f} KB, {WIDTH}x{HEIGHT})"
        )
        return out
