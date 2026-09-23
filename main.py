"""미국 유동성 지표 주간 브리핑. 수집부터 MQWAY 게시까지.

  python main.py               전체 실행. 본문만 만들고 전송하지 않는다
  python main.py --send        MQWAY 로 실제 전송까지
  python main.py --check       환경 자가진단. 스케줄러에 걸기 전에 한 번
  python main.py --thumbnail   img/thumbnail.png 생성 (한 번만)

기본값은 보내지 않는 것이다. 실서버에 잘못 올라간 글은 지우기 전까지
되돌릴 수 없으므로 --send 를 명시해야만 전송한다.

전송 실패는 생성 실패가 아니다. post.html 은 이미 저장돼 있어 나중에
다시 보낼 수 있으므로 종료 코드 0 을 유지한다.
"""

from __future__ import annotations

import json
import os
import re
import sys

# 프로젝트 루트 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.api_util import THUMBNAIL_PATH, ApiError, ApiUtil
from utils.config_util import (
    EXPORT_DIR,
    MQWAY_CATEGORY,
    MQWAY_WRITER,
    blocked_ids,
    mqway_endpoint,
)
from utils.fred_util import FredError, FredUtil
from utils.logger_util import LoggerUtil
from utils.preview_util import PreviewUtil
from utils.render_util import (
    DISCLAIMER,
    build_notify_facts,
    post_title,
    render_post,
)
from utils.selftest_util import SelftestUtil
from utils.telegram_util import TelegramUtil
from utils.thumbnail_util import ThumbnailUtil

POST_PATH = EXPORT_DIR / "post.html"
LATEST_PATH = EXPORT_DIR / "latest.json"

# 게시판 목록이 strip_tags() 로 미리보기를 만든다. 이보다 짧으면
# 목록에서 빈 카드처럼 보인다.
PREVIEW_MIN_CHARS = 50


class LiquidityFeedService:
    def __init__(self):
        self.logger = LoggerUtil().get_logger()
        self.fred = FredUtil()
        self.api = ApiUtil()
        self.telegram = TelegramUtil()
        self.preview = PreviewUtil()
        self.thumbnail = ThumbnailUtil()

    def build(self) -> dict:
        """FRED 에서 받아 post.html 과 latest.json 을 만든다. 스냅샷을 돌려준다."""
        data, sources = self.fred.collect()
        snapshot = self.fred.build_snapshot(data, sources)

        body = render_post(snapshot)
        POST_PATH.parent.mkdir(parents=True, exist_ok=True)
        POST_PATH.write_text(body, encoding="utf-8")

        # latest.json 은 게시물과 별개 산출물이다. charts 와 labels 는 게시물
        # 전용이라 빼고, 시리즈별 출처 기관은 여기에 전부 싣는다(법적 의무 3).
        latest = {
            "meta": snapshot["meta"],
            "layers": snapshot["layers"],
            "derived": snapshot["derived"],
        }
        LATEST_PATH.write_text(
            json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self.logger.info(f"산출물: {POST_PATH}")
        self.logger.info(f"        {LATEST_PATH}")
        return snapshot

    def verify(self, body: str, snapshot: dict) -> bool:
        """MQWAY 제약을 본문에 대고 검사한다. 전부 통과해야 보낸다."""
        size = len(body.encode("utf-8"))
        preview = re.sub(r"<(script|style)[^>]*>.*?</>", " ", body, flags=re.S)
        preview = re.sub(r"<[^>]+>", " ", preview).strip()
        preview = re.sub(r"\s+", " ", preview)[:200]
        lede_ok = body.index('class="lf-sum"') < body.index("lf-chart")
        no_blocked = not any(b in body for b in blocked_ids())

        checks = [
            (f"본문 64KB 미만 (실제 {size:,} bytes, 여유 {65536 - size:,})", size < 65536),
            ("최상단에 개조식 텍스트 요약이 있다", lede_ok),
            ("strip_tags 미리보기가 비지 않는다", len(preview) > PREVIEW_MIN_CHARS),
            ("게시 금지 시리즈가 본문에 없다", no_blocked),
            ("FRED 면책 문구가 들어 있다", DISCLAIMER in body),
            ("ECharts 5.4.3 을 직접 불러온다", "echarts@5.4.3" in body),
            # 본문 출처는 FRED 한 줄로 줄였다. 시리즈별 기관과 인용 정보는
            # latest.json 의 meta.sources 가 담당한다(법적 의무 3).
            ("본문 출처가 FRED 한 줄이다", "<p>출처 FRED</p>" in body),
            ("기관 정보가 스냅샷 meta.sources 에 있다", len(snapshot["meta"]["sources"]) > 0),
        ]

        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("MQWAY 제약 검사")
        self.logger.info("=" * 70)
        for label, ok in checks:
            self.logger.info(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        self.logger.info("")
        self.logger.info("미리보기 첫 200자:")
        self.logger.info(f"  {preview}")
        return all(ok for _, ok in checks)

    def publish(self, title: str, body: str, facts: list[str], send: bool) -> dict | None:
        """게시. 실패해도 예외를 내지 않고 None 을 돌려준다.

        send 가 False 면 검사만 하고 보내지 않는다.
        """
        try:
            self.api.check_payload(title, body, MQWAY_CATEGORY, MQWAY_WRITER)
        except ApiError as exc:
            self.logger.error(f"게시 전 검사 실패: {exc.message}")
            self.telegram.send_error(
                self.telegram.failure_message("게시 전 검사", exc.message)
            )
            return None

        if not send:
            self.logger.info("[전송 안 함] --send 를 붙여야 실제로 게시된다")
            self.logger.info(f"  대상   {mqway_endpoint()}")
            self.logger.info(f"  제목   {title}")
            self.logger.info(f"  분류   {MQWAY_CATEGORY} / 작성자 {MQWAY_WRITER}")
            self.logger.info(f"  본문   {len(body.encode('utf-8')):,} B")
            self.logger.info(
                f"  썸네일 {THUMBNAIL_PATH.name if THUMBNAIL_PATH.exists() else '없음'}"
            )
            return None

        try:
            result = self.api.create_post(title, body)
        except ApiError as exc:
            self.logger.error(f"게시 실패: {exc.message}")
            self.telegram.send_error(
                self.telegram.failure_message("MQWAY 전송", exc.message)
            )
            return None

        url = self.api.post_url(result)
        self.logger.info(f"게시 완료: {url or '(링크 확인 실패)'}")
        self.telegram.send_message(self.telegram.success_message(title, url, facts))
        return result

    def run(self, send: bool = False) -> int:
        """수집 -> 본문 생성 -> 검사 -> 확인용 문서 -> 게시."""
        try:
            snapshot = self.build()
        except FredError as exc:
            self.logger.error(f"수집 실패: {exc}")
            self.telegram.send_error(self.telegram.failure_message("FRED 수집", str(exc)))
            return 2

        body = POST_PATH.read_text(encoding="utf-8")
        as_of = snapshot["meta"]["as_of_label"]

        if not self.verify(body, snapshot):
            self.logger.error("MQWAY 제약 검사 실패. 게시하지 않는다")
            return 1

        self.preview.build(body, as_of)
        self.publish(
            post_title(as_of), body, build_notify_facts(snapshot["derived"]), send
        )
        return 0


def main() -> int:
    """메인 실행 함수"""
    args = set(sys.argv[1:])
    service = LiquidityFeedService()

    if "--check" in args:
        return 0 if SelftestUtil().run() else 1

    if "--thumbnail" in args:
        service.thumbnail.build()
        return 0

    return service.run(send="--send" in args)


if __name__ == "__main__":
    sys.exit(main())
