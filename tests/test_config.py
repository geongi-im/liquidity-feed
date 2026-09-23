"""설정 파일 불변식 검사."""

from __future__ import annotations

from utils.config_util import blocked_ids, load_series


def test_series_ids_are_unique():
    ids = [s["id"] for s in load_series()["series"]]
    assert len(ids) == len(set(ids)), "중복 시리즈 ID 가 있다"


def test_blocked_series_never_collected():
    """ICE 저작권 시리즈는 수집 대상에 절대 들어가면 안 된다."""
    ids = {s["id"] for s in load_series()["series"]}
    assert not (ids & blocked_ids())


def test_every_series_has_layer_and_name():
    for s in load_series()["series"]:
        assert "layer" in s, f"{s['id']} 에 layer 가 없다"
        assert s.get("name_ko"), f"{s['id']} 에 name_ko 가 없다"


def test_needed_series_are_declared_and_allowed():
    """FredUtil 이 받는 시리즈는 전부 series.yaml 에 있고 금지 목록 밖이어야 한다."""
    from utils.fred_util import NEEDED

    declared = {s["id"] for s in load_series()["series"]}
    assert set(NEEDED) <= declared, f"선언되지 않은 시리즈: {set(NEEDED) - declared}"
    assert not (set(NEEDED) & blocked_ids())


def test_mqway_endpoint_appends_api(monkeypatch):
    """BASE_URL 은 호스트까지만 받고 /api 는 코드가 붙인다.

    형제 프로젝트 krx-daily-brief 와 같은 규칙이다. 여기가 어긋나면
    /api 없는 주소로 POST 해서 404 가 난다.
    """
    from utils.config_util import mqway_endpoint

    monkeypatch.setenv("BASE_URL", "http://localhost")
    assert mqway_endpoint() == "http://localhost/api/board-research"

    monkeypatch.setenv("BASE_URL", "https://mqway.com/")
    assert mqway_endpoint() == "https://mqway.com/api/board-research"


def test_check_payload_rejects_full_document():
    """완결 문서(preview.html)를 보내려 하면 막아야 한다."""
    import pytest

    from utils.api_util import ApiError, ApiUtil
    from utils.config_util import MQWAY_CATEGORY, MQWAY_WRITER

    with pytest.raises(ApiError, match="완결 문서"):
        ApiUtil.check_payload("제목", "<!doctype html><html><body>x</body></html>",
                              MQWAY_CATEGORY, MQWAY_WRITER)


def test_check_payload_rejects_oversized_content():
    """64KB 를 넘는 본문은 보내기 전에 막아야 한다."""
    import pytest

    from utils.api_util import ApiError, ApiUtil
    from utils.config_util import MQWAY_CATEGORY, MQWAY_WRITER

    with pytest.raises(ApiError, match="상한"):
        ApiUtil.check_payload("제목", "<div>" + "가" * 30000 + "</div>",
                              MQWAY_CATEGORY, MQWAY_WRITER)


def test_publish_swallows_errors(monkeypatch):
    """전송 실패는 생성 실패가 아니다. 예외를 내지 않고 None 을 돌려준다.

    post.html 은 이미 저장돼 있어 나중에 다시 보낼 수 있으므로
    호출부가 종료 코드 0 을 유지할 수 있어야 한다.
    """
    from main import LiquidityFeedService

    monkeypatch.setenv("BASE_URL", "http://localhost")
    service = LiquidityFeedService()
    assert service.publish("제목", "<!doctype html><html></html>", [], send=True) is None


def test_publish_without_send_does_not_post(monkeypatch):
    """--send 없이는 전송하지 않는다."""
    from main import LiquidityFeedService

    monkeypatch.setenv("BASE_URL", "http://localhost")
    service = LiquidityFeedService()
    assert service.publish("제목", "<div>본문</div>", [], send=False) is None


def test_base_url_is_required(monkeypatch):
    """BASE_URL 이 없으면 막는다. 기본값이 있으면 운영 서버로 글이 올라간다."""
    import pytest

    from utils.config_util import MissingSettingError, mqway_endpoint

    monkeypatch.delenv("BASE_URL", raising=False)
    with pytest.raises(MissingSettingError, match="BASE_URL"):
        mqway_endpoint()
