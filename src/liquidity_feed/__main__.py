"""CLI 진입점.

python -m liquidity_feed fetch [--series ID] [--full | --incremental]
python -m liquidity_feed derive
python -m liquidity_feed export
python -m liquidity_feed publish [--send]
python -m liquidity_feed check
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="liquidity_feed")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="FRED 에서 시리즈를 수집한다")
    p_fetch.add_argument("--series", help="특정 시리즈 ID 하나만 수집")
    mode = p_fetch.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="전체 재적재")
    mode.add_argument("--incremental", action="store_true", help="증분 수집 (기본)")

    sub.add_parser("derive", help="파생 지표를 계산한다")
    sub.add_parser("export", help="JSON 스냅샷을 생성한다")
    sub.add_parser("check", help="환경 자가진단. 스케줄러에 걸기 전에 한 번 돌린다")

    # 기본값은 보내지 않는 것이다. 실서버에 잘못 올라간 글은 지우기 전까지
    # 되돌릴 수 없으므로 --send 를 명시해야만 전송한다.
    p_pub = sub.add_parser("publish", help="MQWAY 에 게시한다 (기본: 전송 안 함)")
    p_pub.add_argument("--send", action="store_true",
                       help="실제로 MQWAY 에 전송한다. 붙이지 않으면 검사만 한다")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "check":
        from .selftest import run

        return 0 if run() else 1

    raise SystemExit(f"'{args.command}' 는 아직 구현되지 않았다")


if __name__ == "__main__":
    sys.exit(main())
