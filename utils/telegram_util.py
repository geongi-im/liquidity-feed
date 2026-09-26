"""텔레그램 알림.

스케줄러가 토요일 새벽에 돌다가 조용히 실패하면 아무도 모른다.
성공하면 게시물 링크를, 실패하면 사유를 보낸다.

형제 프로젝트 krx-daily-brief 와 같은 환경변수 이름을 쓴다.
  TELEGRAM_BOT_TOKEN       봇 토큰
  TELEGRAM_CHAT_ID         운영 알림이 가는 방
  TELEGRAM_CHAT_TEST_ID    실패와 테스트 알림이 가는 방

**알림 실패는 작업 실패가 아니다.** 게시글이 이미 올라갔는데 알림이 안 갔다고
전체를 실패로 만들면 안 된다. 이 클래스의 메서드는 예외를 밖으로 내지 않고
성공 여부를 bool 로 돌려준다.
"""

from __future__ import annotations

import html as html_mod
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from utils.logger_util import LoggerUtil

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "https://api.telegram.org"
TIMEOUT_SEC = 15.0


def env(name: str) -> str:
    return os.getenv(name, "").strip()


class TelegramUtil:
    def __init__(self):
        self.logger = LoggerUtil().get_logger()

    def is_configured(self) -> bool:
        """토큰과 방 번호가 있는지. 없으면 알림을 건너뛴다."""
        return bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"))

    def _send(self, chat_id: str, text: str) -> bool:
        token = env("TELEGRAM_BOT_TOKEN")
        if not token or not chat_id:
            self.logger.debug("텔레그램 설정이 없어 알림을 건너뛴다")
            return False
        try:
            resp = httpx.post(
                f"{API}/bot{token}/sendMessage",
                data={"chat_id": chat_id, "parse_mode": "HTML", "text": text},
                timeout=TIMEOUT_SEC,
            )
        # 알림 실패로 작업을 죽이지 않는다. 예외 메시지에는 봇 토큰이 든
        # 요청 URL 이 들어가므로 예외 종류만 남긴다.
        except Exception as exc:
            self.logger.error(f"텔레그램 전송 실패 (chat_id={chat_id}): {type(exc).__name__}")
            return False

        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code != 200 or not body.get("ok"):
            reason = body.get("description") or resp.text[:120]
            self.logger.error(
                f"텔레그램 전송 실패 (chat_id={chat_id}): HTTP {resp.status_code} {reason}"
            )
            return False

        # 받아준 방 이름을 남긴다. 엉뚱한 방으로 가도 로그로 알아챌 수 있다.
        chat = body.get("result", {}).get("chat", {})
        name = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
        self.logger.info(f"텔레그램 전송 완료 (chat_id={chat_id}, 방 {name})")
        return True

    def send_message(self, text: str) -> bool:
        """운영 방으로 보낸다."""
        return self._send(env("TELEGRAM_CHAT_ID"), text)

    def send_error(self, text: str) -> bool:
        """실패 방으로 보낸다. 없으면 운영 방으로 보낸다."""
        return self._send(env("TELEGRAM_CHAT_TEST_ID") or env("TELEGRAM_CHAT_ID"), text)

    @staticmethod
    def success_message(title: str, url: str | None, facts: list[str]) -> str:
        """게시 성공 알림 본문. parse_mode 가 HTML 이라 escape 가 필요하다.

        훑어보는 알림이라 짧게 유지한다. 제목, 핵심 수치 몇 줄, 링크로 끝낸다.
        자세한 내용은 게시물을 열어서 본다. facts 는
        report_generator.build_notify_facts() 가 만든다.
        """
        lines = [f"📈 <b>{html_mod.escape(title)}</b>", ""]
        lines += [html_mod.escape(line) for line in facts]
        lines.append("")
        if url:
            # 문구 링크로 건다. 주소를 그대로 노출하면 텔레그램이 누를 수 있는
            # 링크로 만들어 주지 않는 경우가 있다.
            safe = html_mod.escape(url, quote=True)
            lines.append(f'<a href="{safe}">게시물 열기</a>')
        else:
            lines.append("(게시물 링크를 확인하지 못했습니다. 게시판에서 확인하세요)")
        return "\n".join(lines)

    @staticmethod
    def failure_message(stage: str, detail: str) -> str:
        """실패 알림 본문. stage 는 어느 단계에서 깨졌는지."""
        return (
            f"<b>[liquidity-feed] {html_mod.escape(stage)} 실패</b>\n\n"
            f"{html_mod.escape(detail[:600])}"
        )
