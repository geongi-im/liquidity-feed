"""로그 설정.

스케줄러로 돌면 화면 출력이 사라진다. 토요일 새벽에 무슨 일이 있었는지
나중에 확인하려면 파일에 남아 있어야 한다. 형제 프로젝트 krx-daily-brief 와
같은 자리(logs/)에 날짜별로 쌓는다.

날짜는 실행 시각의 로컬 기준이다. 스케줄이 한국시간 토요일 08:00 이므로
서버 시간대가 Asia/Seoul 이어야 파일 이름이 기대대로 나온다.
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"


class LoggerUtil:
    """파일과 화면에 함께 남기는 로거. 여러 번 만들어도 핸들러가 겹치지 않는다."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if LoggerUtil._initialized:
            return

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{date.today().isoformat()}_log.log"

        self.logger = logging.getLogger("liquidity_feed")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.handlers.clear()

        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        self.logger.addHandler(file_handler)

        # 한국어 콘솔(cp949)에서 깨지지 않게 한다
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(console)

        LoggerUtil._initialized = True

    def get_logger(self) -> logging.Logger:
        return self.logger


# 모듈 테스트용
if __name__ == "__main__":
    LoggerUtil().get_logger().info("로거 테스트 메시지")
