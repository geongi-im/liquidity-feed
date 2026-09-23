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

import os
import re
import sys
from pathlib import Path

# 프로젝트 루트 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import httpx
import yaml

from fred_service import (
    CONFIG_DIR,
    FredDataCollector,
    FredError,
    LiquidityCalculator,
    api_key,
    blocked_ids,
    load_series,
    load_thresholds,
)
from report_generator import (
    DISCLAIMER,
    THUMBNAIL_PATH,
    ReportGenerator,
    build_notify_facts,
    post_title,
)
from utils.api_util import (
    ApiError,
    ApiUtil,
    MissingSettingError,
    base_url,
    mqway_endpoint,
)
from utils.logger_util import LOG_DIR, LoggerUtil
from utils.telegram_util import TelegramUtil

# 게시판 카테고리와 작성자. 형제 프로젝트들이 카테고리로 주제를 나눈다
# (krx-daily-brief 는 '시황'). 서버 검증은 max:50 문자열이라 값 제약은 없다.
MQWAY_CATEGORY = "유동성"
MQWAY_WRITER = "admin"

# 게시판 목록이 strip_tags() 로 미리보기를 만든다. 이보다 짧으면
# 목록에서 빈 카드처럼 보인다.
PREVIEW_MIN_CHARS = 50

FRED_PING = "https://api.stlouisfed.org/fred/series"

# 자가진단에서 없어도 게시 자체는 되는 항목. 실패가 아니라 경고로 다룬다.
CHECK_OPTIONAL = {"텔레그램 알림", "썸네일"}


class LiquidityFeedService:
    def __init__(self):
        self.logger = LoggerUtil().get_logger()
        self.collector = FredDataCollector()
        self.calculator = LiquidityCalculator()
        self.report = ReportGenerator()
        self.api = ApiUtil()
        self.telegram = TelegramUtil()

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
            result = self.api.create_post(
                title=title,
                content=body,
                category=MQWAY_CATEGORY,
                writer=MQWAY_WRITER,
                thumbnail_path=THUMBNAIL_PATH,
            )
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
            data, sources = self.collector.collect()
            snapshot = self.calculator.build_snapshot(data, sources)
        except FredError as exc:
            self.logger.error(f"수집 실패: {exc}")
            self.telegram.send_error(self.telegram.failure_message("FRED 수집", str(exc)))
            return 2

        body = self.report.create_post(snapshot)
        as_of = snapshot["meta"]["as_of_label"]

        if not self.verify(body, snapshot):
            self.logger.error("MQWAY 제약 검사 실패. 게시하지 않는다")
            return 1

        self.report.create_preview(body, as_of)
        self.publish(
            post_title(as_of), body, build_notify_facts(snapshot["derived"]), send
        )
        return 0

    # --- 환경 자가진단 ---
    #
    # 스케줄러에 걸기 전에 한 번 돌려서 빠진 설정을 찾는다. 토요일 새벽에
    # 처음 알게 되는 것보다 낫다.

    @staticmethod
    def _check(fn) -> tuple[bool, str]:
        try:
            return fn()
        # 진단이 예외로 멈추면 안 된다
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _check_fred_key(self):
        key = api_key()
        if not key:
            return False, "FRED_API_KEY 가 없다. .env 에 설정한다"
        return True, f"설정됨 (길이 {len(key)})"

    def _check_fred_reach(self):
        key = api_key()
        if not key:
            return False, "키가 없어 건너뜀"
        resp = httpx.get(
            FRED_PING,
            params={"series_id": "WALCL", "api_key": key, "file_type": "json"},
            timeout=20.0,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
        title = resp.json()["seriess"][0]["title"]
        return True, f"응답 정상 ({title[:40]}...)"

    def _check_mqway_setting(self):
        try:
            return True, mqway_endpoint()
        except MissingSettingError as exc:
            return False, str(exc)

    def _check_mqway_reach(self):
        try:
            site = base_url()
        except MissingSettingError:
            return False, "BASE_URL 이 없어 건너뜀"
        try:
            resp = httpx.get(site, timeout=15.0, follow_redirects=True)
        except httpx.RequestError as exc:
            return False, f"{site} 접속 실패: {type(exc).__name__}"
        return resp.status_code < 500, f"{site} -> HTTP {resp.status_code}"

    def _check_series(self):
        ids = [s["id"] for s in load_series()["series"]]
        if len(ids) != len(set(ids)):
            return False, "중복 시리즈 ID 가 있다"
        overlap = set(ids) & blocked_ids()
        if overlap:
            return False, f"게시 금지 시리즈가 섞여 있다: {overlap}"
        return True, f"{len(ids)}개, 금지 {len(blocked_ids())}개 제외 확인"

    def _check_thresholds(self):
        thr = load_thresholds()
        metrics = thr.get("metrics", {})
        missing = [k for k, v in metrics.items() if not v.get("gloss")]
        if missing:
            return False, f"해설 문구가 빈 지표: {missing}"
        return True, f"지표 {len(metrics)}개, 시리즈 {len(thr.get('series', {}))}개"

    def _check_schedule(self):
        path = CONFIG_DIR / "schedule.yaml"
        if not path.exists():
            return False, "config/schedule.yaml 이 없다"
        sch = yaml.safe_load(path.read_text(encoding="utf-8"))
        return True, f"{sch['run']['cron']} ({sch['run']['timezone']})"

    def _check_thumbnail(self):
        if not THUMBNAIL_PATH.exists():
            return False, (
                f"{THUMBNAIL_PATH.name} 이 없다. python main.py --thumbnail 로 만든다"
            )
        kb = THUMBNAIL_PATH.stat().st_size / 1024
        return True, f"{THUMBNAIL_PATH.name} ({kb:.1f} KB)"

    def _check_telegram(self):
        if not self.telegram.is_configured():
            return False, (
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없다. "
                "실패해도 알림이 가지 않는다"
            )
        return True, "설정됨"

    def _check_logs(self):
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        return True, str(LOG_DIR)

    def check_environment(self) -> bool:
        """전부 통과하면 True."""
        checks = [
            ("FRED API 키", self._check_fred_key),
            ("FRED 접속", self._check_fred_reach),
            ("MQWAY 주소", self._check_mqway_setting),
            ("MQWAY 접속", self._check_mqway_reach),
            ("series.yaml", self._check_series),
            ("thresholds.yaml", self._check_thresholds),
            ("schedule.yaml", self._check_schedule),
            ("썸네일", self._check_thumbnail),
            ("텔레그램 알림", self._check_telegram),
            ("로그 디렉터리", self._check_logs),
        ]
        results = [(label, *self._check(fn)) for label, fn in checks]

        self.logger.info("환경 자가진단")
        self.logger.info("=" * 68)
        for label, ok, detail in results:
            self.logger.info(f"  [{'OK  ' if ok else 'FAIL'}] {label:<16} {detail}")
        self.logger.info("=" * 68)
        self.logger.info(f"게시 설정: 분류 {MQWAY_CATEGORY} / 작성자 {MQWAY_WRITER}")

        # 텔레그램과 썸네일이 없어도 게시 자체는 된다. 필수만 실패로 본다
        required_ok = all(ok for label, ok, _ in results if label not in CHECK_OPTIONAL)
        warned = [label for label, ok, _ in results if not ok and label in CHECK_OPTIONAL]

        if warned:
            self.logger.warning(
                f"경고: {', '.join(warned)} 미설정. 동작은 하지만 권장하지 않는다"
            )
        self.logger.info(f"결과: {'정상' if required_ok else '실패'}")
        return required_ok


def main() -> int:
    """메인 실행 함수"""
    args = set(sys.argv[1:])
    service = LiquidityFeedService()

    if "--check" in args:
        return 0 if service.check_environment() else 1

    if "--thumbnail" in args:
        service.report.create_thumbnail()
        return 0

    return service.run(send="--send" in args)


if __name__ == "__main__":
    sys.exit(main())
