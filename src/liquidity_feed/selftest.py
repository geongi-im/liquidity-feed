"""환경 자가진단.

스케줄러에 걸기 전에 한 번 돌려서 빠진 설정을 찾는다. 토요일 새벽에
처음 알게 되는 것보다 낫다.

  python -m liquidity_feed check
"""

from __future__ import annotations

import httpx

from . import notify
from .config import (
    CONFIG_DIR,
    MQWAY_CATEGORY,
    MQWAY_WRITER,
    MissingSettingError,
    base_url,
    blocked_ids,
    env,
    load_series,
    load_thresholds,
    mqway_endpoint,
)
from .logging_util import LOG_DIR, get_logger
from .publish import THUMBNAIL_PATH

logger = get_logger()

FRED_PING = "https://api.stlouisfed.org/fred/series"


def _check(label: str, fn) -> tuple[bool, str]:
    try:
        ok, detail = fn()
    # 진단이 예외로 멈추면 안 된다
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return ok, detail


def run() -> bool:
    """전부 통과하면 True."""
    results: list[tuple[str, bool, str]] = []

    def fred_key():
        key = env("FRED_API_KEY")
        if not key:
            return False, "FRED_API_KEY 가 없다. .env 에 설정한다"
        return True, f"설정됨 (길이 {len(key)})"

    def fred_reach():
        key = env("FRED_API_KEY")
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

    def mqway_setting():
        try:
            return True, mqway_endpoint()
        except MissingSettingError as exc:
            return False, str(exc)

    def mqway_reach():
        try:
            site = base_url()
        except MissingSettingError:
            return False, "BASE_URL 이 없어 건너뜀"
        try:
            resp = httpx.get(site, timeout=15.0, follow_redirects=True)
        except httpx.RequestError as exc:
            return False, f"{site} 접속 실패: {type(exc).__name__}"
        return resp.status_code < 500, f"{site} -> HTTP {resp.status_code}"

    def series_cfg():
        cfg = load_series()
        ids = [s["id"] for s in cfg["series"]]
        if len(ids) != len(set(ids)):
            return False, "중복 시리즈 ID 가 있다"
        overlap = set(ids) & blocked_ids()
        if overlap:
            return False, f"게시 금지 시리즈가 섞여 있다: {overlap}"
        return True, f"{len(ids)}개, 금지 {len(blocked_ids())}개 제외 확인"

    def thresholds_cfg():
        thr = load_thresholds()
        metrics = thr.get("metrics", {})
        missing = [k for k, v in metrics.items() if not v.get("gloss")]
        if missing:
            return False, f"해설 문구가 빈 지표: {missing}"
        return True, f"지표 {len(metrics)}개, 시리즈 {len(thr.get('series', {}))}개"

    def schedule_cfg():
        path = CONFIG_DIR / "schedule.yaml"
        if not path.exists():
            return False, "config/schedule.yaml 이 없다"
        import yaml

        sch = yaml.safe_load(path.read_text(encoding="utf-8"))
        return True, f"{sch['run']['cron']} ({sch['run']['timezone']})"

    def thumbnail():
        if not THUMBNAIL_PATH.exists():
            return False, (
                f"{THUMBNAIL_PATH.name} 이 없다. "
                "python scripts/make_thumbnail.py 로 만든다"
            )
        kb = THUMBNAIL_PATH.stat().st_size / 1024
        return True, f"{THUMBNAIL_PATH.name} ({kb:.1f} KB)"

    def telegram():
        if not notify.is_configured():
            return False, (
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없다. "
                "실패해도 알림이 가지 않는다"
            )
        return True, "설정됨"

    def logs():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        return True, str(LOG_DIR)

    for label, fn in [
        ("FRED API 키", fred_key),
        ("FRED 접속", fred_reach),
        ("MQWAY 주소", mqway_setting),
        ("MQWAY 접속", mqway_reach),
        ("series.yaml", series_cfg),
        ("thresholds.yaml", thresholds_cfg),
        ("schedule.yaml", schedule_cfg),
        ("썸네일", thumbnail),
        ("텔레그램 알림", telegram),
        ("로그 디렉터리", logs),
    ]:
        ok, detail = _check(label, fn)
        results.append((label, ok, detail))

    logger.info("환경 자가진단")
    logger.info("=" * 68)
    for label, ok, detail in results:
        logger.info(f"  [{'OK  ' if ok else 'FAIL'}] {label:<16} {detail}")
    logger.info("=" * 68)
    logger.info(f"게시 설정: 분류 {MQWAY_CATEGORY} / 작성자 {MQWAY_WRITER}")

    # 텔레그램과 썸네일이 없어도 게시 자체는 된다. 필수만 실패로 본다
    optional = {"텔레그램 알림", "썸네일"}
    required_ok = all(ok for label, ok, _ in results if label not in optional)
    warned = [label for label, ok, _ in results if not ok and label in optional]

    if warned:
        logger.warning(f"경고: {', '.join(warned)} 미설정. 동작은 하지만 권장하지 않는다")
    logger.info(f"결과: {'정상' if required_ok else '실패'}")
    return required_ok
