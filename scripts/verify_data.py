"""수집 데이터 일치 점검.

같은 시리즈를 서로 다른 두 경로로 받아 값이 일치하는지 대조한다.
  A. 공식 API  /fred/series/observations
  B. 개발 확인용 CSV  fredgraph.csv

두 경로가 겹치는 날짜에서 값이 다르면 수집 로직이나 FRED 쪽에 문제가 있다.
덧붙여 내부 산술 항등식과 README 검증 기준을 함께 확인한다.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_OBS = "https://api.stlouisfed.org/fred/series/observations"
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CALL_DELAY_SEC = 0.5

# 값 비교 허용 오차. FRED 는 소수 4자리까지 주므로 그보다 작게 잡는다.
TOLERANCE = 1e-9


def parse_value(raw: str) -> float | None:
    raw = raw.strip()
    return None if raw in (".", "", "NA") else float(raw)


def fetch_api(client: httpx.Client, sid: str, key: str) -> dict[date, float | None]:
    resp = client.get(
        API_OBS,
        params={"series_id": sid, "api_key": key, "file_type": "json"},
        timeout=60.0,
    )
    resp.raise_for_status()
    return {
        date.fromisoformat(o["date"]): parse_value(o["value"])
        for o in resp.json()["observations"]
    }


def fetch_csv(client: httpx.Client, sid: str) -> dict[date, float | None]:
    resp = client.get(CSV_URL, params={"id": sid}, timeout=60.0)
    resp.raise_for_status()
    out: dict[date, float | None] = {}
    for line in resp.text.strip().splitlines()[1:]:
        if not line.strip():
            continue
        d_str, _, v_str = line.partition(",")
        out[date.fromisoformat(d_str)] = parse_value(v_str)
    return out


def compare(a: dict, b: dict) -> tuple[int, int, float, list]:
    """겹치는 날짜에서 값을 비교한다. (겹침수, 불일치수, 최대차이, 예시)"""
    shared = sorted(set(a) & set(b))
    diffs = []
    max_diff = 0.0
    for d in shared:
        va, vb = a[d], b[d]
        if va is None and vb is None:
            continue
        if va is None or vb is None:
            diffs.append((d, va, vb))
            continue
        gap = abs(va - vb)
        max_diff = max(max_diff, gap)
        if gap > TOLERANCE:
            diffs.append((d, va, vb))
    return len(shared), len(diffs), max_diff, diffs[:3]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        print("FRED_API_KEY 가 없다. .env 를 확인한다.")
        return 2

    cfg = yaml.safe_load((ROOT / "config" / "series.yaml").read_text(encoding="utf-8"))
    ids = [s["id"] for s in cfg["series"]]

    print("=" * 78)
    print("1. 두 경로 값 대조 (공식 API vs fredgraph CSV)")
    print("=" * 78)

    store: dict[str, dict[date, float | None]] = {}
    failures = []
    with httpx.Client(headers={"User-Agent": "liquidity-feed/0.1 verify"}) as client:
        for sid in ids:
            api = fetch_api(client, sid, key)
            time.sleep(CALL_DELAY_SEC)
            csv = fetch_csv(client, sid)
            time.sleep(CALL_DELAY_SEC)
            store[sid] = api

            shared, n_diff, max_diff, samples = compare(api, csv)
            missing = len(api) - shared
            mark = "OK  " if n_diff == 0 else "DIFF"
            if n_diff:
                failures.append(sid)
            print(
                f"[{mark}] {sid:<16} API {len(api):>5}  CSV {len(csv):>5}  "
                f"겹침 {shared:>5}  불일치 {n_diff:>3}  최대차 {max_diff:.2e}"
                f"{'   CSV 누락 ' + str(missing) + '행' if missing else ''}"
            )
            for d, va, vb in samples:
                print(f"         {d}  API={va}  CSV={vb}")

    print()
    print("=" * 78)
    print("2. 내부 산술 항등식 (2026-09-16 수요일 기준)")
    print("=" * 78)
    wed = date(2026, 9, 16)

    def v(sid: str) -> float:
        return store[sid][wed]

    checks = []
    sho, tsl, mcb, walcl = v("WSHOSHO"), v("WSHOTSL"), v("WSHOMCB"), v("WALCL")
    print(f"  WSHOTSL + WSHOMCB = {tsl + mcb:>12,.0f} M   <= WSHOSHO {sho:>12,.0f} M")
    checks.append(("국채 + MBS <= 보유증권 전체", tsl + mcb <= sho))
    print(f"  WSHOSHO           = {sho:>12,.0f} M   <= WALCL    {walcl:>12,.0f} M")
    checks.append(("보유증권 전체 <= 총자산", sho <= walcl))
    resid = sho - (tsl + mcb)
    print(f"  잔차(에이전시채 등) = {resid:>12,.0f} M")
    checks.append(("잔차가 음수가 아니다", resid >= 0))

    tga_avg, tga_wed = v("WTREGEN"), v("WDTGAL")
    res_avg, res_wed = v("WRESBAL"), v("WRBWFRBL")
    print(f"  TGA  주간평균 {tga_avg:>12,.0f} M  /  수요일 {tga_wed:>12,.0f} M")
    print(f"  지준 주간평균 {res_avg:>12,.0f} M  /  수요일 {res_wed:>12,.0f} M")
    checks.append(("TGA 두 측정치가 같은 자릿수", 0.5 < tga_wed / tga_avg < 2.0))
    checks.append(("지준 두 측정치가 같은 자릿수", 0.5 < res_wed / res_avg < 2.0))

    print()
    print("=" * 78)
    print("3. 데이터 형태 점검")
    print("=" * 78)
    for sid in ids:
        obs = store[sid]
        dates = sorted(obs)
        nulls = sum(1 for d in dates if obs[d] is None)
        monotonic = dates == sorted(set(dates))
        flag = ""
        if not monotonic:
            flag += " 날짜중복/역순"
        if nulls:
            flag += f" 결측 {nulls}건"
        if flag:
            print(f"  {sid:<16}{flag}")
    print("  (위에 아무것도 없으면 중복 날짜 없고 결측도 없다)")

    print()
    print("=" * 78)
    print("4. README 검증 기준")
    print("=" * 78)
    blocked = {b["id"] for b in cfg["blocked"]}
    criteria = [
        ("1. 게시 금지 시리즈가 수집 목록에 없다", not (set(ids) & blocked)),
        ("2. WRESBAL 2026-09-16 = 3013794", v("WRESBAL") == 3013794.0),
        ("3. WTREGEN 2026-09-16 = 877028", v("WTREGEN") == 877028.0),
        ("4. 환산 후 지준 = 3.013794 조", abs(v("WRESBAL") / 1e6 - 3.013794) < 1e-9),
    ]
    for label, ok in criteria + checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    all_ok = not failures and all(ok for _, ok in criteria + checks)
    print()
    print(f"결론: {'모두 일치' if all_ok else '불일치 있음 -> ' + ', '.join(failures)}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
