"""post.html 을 브라우저에서 열어볼 수 있는 최소 문서로 감싼다.

담는 것은 실제로 MQWAY 에 올라갈 본문뿐이다. 하네스나 설명, 검사 결과
같은 것은 넣지 않는다. 화면에 보이는 것이 곧 게시물에 보일 것이다.

감싸개가 하는 일은 세 가지뿐이고 모두 MQWAY 페이지가 이미 해 주는 것이다.
  - <meta charset="utf-8">. 없으면 윈도우 브라우저가 cp949 로 읽어 한글이 깨진다
  - Noto Sans KR / Outfit 로드. MQWAY 가 전역으로 부른다
  - 페이지 배경 #F8F9FA 와 기본 서체. MQWAY body 의 값 그대로다

본문 자체는 한 글자도 바꾸지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from utils.config_util import EXPORT_DIR
from utils.logger_util import LoggerUtil
from utils.render_util import post_title

POST_PATH = EXPORT_DIR / "post.html"
PREVIEW_PATH = EXPORT_DIR / "preview.html"

# mqway.com 의 body 설정값. 게시물이 실제로 놓이는 바닥을 그대로 재현한다.
PAGE_CSS = (
    "body{margin:0;padding:20px 16px;background:#F8F9FA;color:#2D3047;"
    "font-family:'Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif}"
    ".mq-page{max-width:860px;margin:0 auto}"
)

FONTS = (
    "https://fonts.googleapis.com/css2"
    "?family=Outfit:wght@400;500;600"
    "&family=Noto+Sans+KR:wght@400;500;600;700&display=swap"
)


class PreviewUtil:
    def __init__(self):
        self.logger = LoggerUtil().get_logger()

    def build(self, fragment: str, as_of_label: str, out: Path = PREVIEW_PATH) -> Path:
        """본문 조각을 감싼 확인용 문서를 만든다."""
        title = post_title(as_of_label)
        page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="mq-page">
{fragment}
</div>
</body>
</html>"""

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")

        body_size = len(fragment.encode("utf-8"))
        self.logger.info(
            f"본문 {body_size:,} B (MQWAY 상한 65,536 B, 여유 {65536 - body_size:,} B)"
        )
        self.logger.info(f"감싸개까지 {len(page.encode('utf-8')):,} B")
        self.logger.info(f"확인용 문서: {out}")
        self.logger.info(f"브라우저에서 열기: {out.as_uri()}")
        return out
