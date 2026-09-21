"""설정 로딩.

시리즈 정의와 임계치, 게시물 문구는 코드가 아니라 config/*.yaml 에 둔다.
단위와 주기도 여기서 정하지 않는다. FRED /fred/series 응답을 받아 그대로
쓰고, 환산 로직이 그 값을 참조한다.

이 프로젝트는 DB 를 쓰지 않는다. FRED 가 호출마다 전체 히스토리를 주고
최종 결과는 MQWAY 에 적재되므로 중간에 둘 저장소가 필요 없다.
단계 사이에 데이터를 넘길 때는 data/raw 아래 원본 응답 파일을 쓴다.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXPORT_DIR = DATA_DIR / "export"

load_dotenv(ROOT / ".env")

class MissingSettingError(RuntimeError):
    """필수 환경변수가 없을 때. 어떤 값을 어떻게 채우는지 메시지에 담는다."""


# MQWAY 게시 설정.
#
# BASE_URL 은 스킴과 호스트까지만 적는다. /api 는 코드가 붙인다.
# 형제 프로젝트(krx-daily-brief)가 같은 규칙을 쓰므로 .env 를 공유할 수 있다.
#   BASE_URL=http://localhost   ->  http://localhost/api/board-research
#
# 게시판과 작성자는 바뀌지 않으므로 여기 고정한다.
# board-* 엔드포인트에는 인증 미들웨어가 없다. 키 없이 URL 로 바로 POST 한다.
MQWAY_BOARD = "board-research"
MQWAY_WRITER = "admin"

# 게시판 카테고리. 형제 프로젝트들이 카테고리로 주제를 나눈다
# (krx-daily-brief 는 '시황'). 서버 검증은 max:50 문자열이라 값 제약은 없다.
MQWAY_CATEGORY = "유동성"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def base_url() -> str:
    """사이트 주소. 스킴과 호스트까지만. 게시물 조회 URL 조립에도 쓴다.

    기본값을 두지 않는다. 기본값이 있으면 .env 를 빠뜨린 채 실행했을 때
    운영 서버로 글이 올라간다. 형제 프로젝트도 같은 이유로 막아둔다.
    """
    value = env("BASE_URL")
    if not value:
        raise MissingSettingError(
            "환경변수 BASE_URL 이 없다. .env 에 설정한다 (.env.example 참고). "
            "예) BASE_URL=http://localhost"
        )
    return value.rstrip("/")


def mqway_endpoint() -> str:
    """게시물을 POST 할 주소."""
    return f"{base_url()}/api/{MQWAY_BOARD}"


def load_series() -> dict:
    """config/series.yaml 을 읽는다."""
    return yaml.safe_load((CONFIG_DIR / "series.yaml").read_text(encoding="utf-8"))


def load_thresholds() -> dict:
    """config/thresholds.yaml 을 읽는다."""
    return yaml.safe_load((CONFIG_DIR / "thresholds.yaml").read_text(encoding="utf-8"))


def blocked_ids() -> set[str]:
    """게시 금지 시리즈 ID 집합. 수집 / 출력 전 단계에서 걸러낸다."""
    return {item["id"] for item in load_series().get("blocked", [])}
