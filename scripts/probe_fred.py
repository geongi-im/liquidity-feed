"""FRED 수집 가능성 점검 스크립트.

config/series.yaml 의 시리즈를 실제로 한 번씩 받아보고
- 응답이 오는지
- 관측치가 몇 개인지, 기간이 어디부터 어디까지인지
- 날짜 간격으로 추정한 주기가 기대값과 맞는지
- 최신값 크기가 기대 단위와 어긋나지 않는지
를 표로 출력하고 data/probe_report.json 에 남긴다.

FRED_API_KEY 가 있으면 공식 API 를, 없으면 README 에 적힌
개발 확인용 CSV 경로를 쓴다. CSV 경로는 메타데이터를 주지 않으므로
units / frequency 확인은 키가 있을 때만 가능하다.
"""

from __future__ import annotations

import itertools
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "series.yaml"
REPORT = ROOT / "data" / "probe_report.json"

# .env 의 FRED_API_KEY 를 읽는다. 이미 환경변수로 들어와 있으면 그쪽이 우선이다.
load_dotenv(ROOT / ".env")

API_URL = "https://api.stlouisfed.org/fred/series/observations"
META_URL = "https://api.stlouisfed.org/fred/series"
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED 는 구체적 rate limit 을 공개하지 않는다. 호출 간 간격을 둔다.
CALL_DELAY_SEC = 0.6
MAX_RETRY = 4

# 날짜 간격 중앙값 -> 주기 이름
FREQ_BUCKETS = [
    (1.9, "Daily"),
    (9.0, "Weekly"),
    (20.0, "Biweekly"),
    (45.0, "Monthly"),
    (120.0, "Quarterly"),
    (400.0, "Annual"),
]


def infer_frequency(dates: list[date]) -> str:
    """관측 날짜 목록에서 주기를 추정한다."""
    if len(dates) < 3:
        return "unknown"
    tail = dates[-40:] if len(dates) > 40 else dates
    gaps = [(b - a).days for a, b in itertools.pairwise(tail) if (b - a).days > 0]
    if not gaps:
        return "unknown"
    med = statistics.median(gaps)
    for limit, name in FREQ_BUCKETS:
        if med <= limit:
            return name
    return f"{med:.0f}d"


def fetch_via_api(client: httpx.Client, series_id: str, api_key: str) -> list[tuple[date, float | None]]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    resp = request_with_backoff(client, "GET", API_URL, params=params)
    payload = resp.json()
    rows = []
    for obs in payload.get("observations", []):
        raw = obs.get("value", ".")
        # FRED 결측치는 "." 로 온다
        value = None if raw == "." else float(raw)
        rows.append((date.fromisoformat(obs["date"]), value))
    return rows


def fetch_via_csv(client: httpx.Client, series_id: str) -> list[tuple[date, float | None]]:
    resp = request_with_backoff(client, "GET", CSV_URL, params={"id": series_id})
    text = resp.text.strip()
    lines = text.splitlines()
    if not lines:
        raise ValueError("빈 응답")
    header = lines[0].split(",")
    if len(header) != 2:
        # id 를 여러 개 넘기면 ZIP 으로 떨어진다. 단건 호출인데 이러면 이상 응답이다.
        raise ValueError(f"예상치 못한 헤더: {lines[0][:80]}")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        d_str, _, v_str = line.partition(",")
        v_str = v_str.strip()
        value = None if v_str in (".", "", "NA") else float(v_str)
        rows.append((date.fromisoformat(d_str), value))
    return rows


def request_with_backoff(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    """429 / 5xx 는 지수 백오프로 재시도한다."""
    delay = 1.0
    last_exc: Exception | None = None
    for _ in range(MAX_RETRY):
        try:
            resp = client.request(method, url, timeout=30.0, **kw)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"{MAX_RETRY}회 재시도 실패: {last_exc}")


def fetch_meta(client: httpx.Client, series_id: str, api_key: str) -> dict:
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    resp = request_with_backoff(client, "GET", META_URL, params=params)
    items = resp.json().get("seriess", [])
    return items[0] if items else {}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    mode = "official API" if api_key else "fredgraph CSV (키 없음, 메타데이터 확인 불가)"
    print(f"수집 경로: {mode}")
    print(f"대상 시리즈: {len(cfg['series'])}개\n")

    results = []
    with httpx.Client(headers={"User-Agent": "liquidity-feed/0.1 probe"}) as client:
        for item in cfg["series"]:
            sid = item["id"]
            row: dict = {
                "id": sid,
                "layer": item["layer"],
                "name_ko": item["name_ko"],
                "expected_units": item.get("expected_units"),
                "expected_frequency": item.get("expected_frequency"),
            }
            try:
                if api_key:
                    obs = fetch_via_api(client, sid, api_key)
                    row["meta"] = fetch_meta(client, sid, api_key)
                    time.sleep(CALL_DELAY_SEC)
                else:
                    obs = fetch_via_csv(client, sid)
                dated = [d for d, _ in obs]
                valued = [(d, v) for d, v in obs if v is not None]
                row["ok"] = True
                row["count"] = len(obs)
                row["null_count"] = len(obs) - len(valued)
                row["first_date"] = dated[0].isoformat() if dated else None
                row["last_date"] = dated[-1].isoformat() if dated else None
                row["last_value"] = valued[-1][1] if valued else None
                row["last_value_date"] = valued[-1][0].isoformat() if valued else None
                row["inferred_frequency"] = infer_frequency(dated)
                # 추론기는 Weekly / Daily 수준만 뱉는다. FRED 의
                # "Weekly, Ending Wednesday" 같은 문자열은 앞 토큰만 비교한다.
                exp_f = (item.get("expected_frequency") or "").split(",")[0].strip().lower()
                row["freq_match"] = row["inferred_frequency"].lower() == exp_f
            # 어떤 실패든 표에 남기고 다음 시리즈로 계속 진행한다
            except Exception as exc:
                row["ok"] = False
                row["error"] = f"{type(exc).__name__}: {exc}"
            results.append(row)
            status = "OK " if row.get("ok") else "FAIL"
            warn = ""
            if not row.get("freq_match", True):
                warn = f" <-- 기대 {item.get('expected_frequency')}"
            print(
                f"[{status}] {sid:<16} {row.get('count', '-'):>7} obs  "
                f"last={row.get('last_value_date', '-')}  "
                f"val={row.get('last_value', '-')}  "
                f"freq={row.get('inferred_frequency', '-')}{warn}"
            )
            meta = row.get("meta") or {}
            if meta:
                print(f"         title : {meta.get('title')}")
                print(
                    f"         units : {meta.get('units')}"
                    f"  |  freq : {meta.get('frequency')}"
                    f"  |  SA : {meta.get('seasonal_adjustment_short')}"
                    f"  |  last_updated : {meta.get('last_updated')}"
                )
                exp_u = (item.get("expected_units") or "").lower()
                act_u = (meta.get("units") or "").lower()
                row["units_match"] = exp_u in act_u if exp_u else None
                row["meta_freq_match"] = (
                    (meta.get("frequency") or "").lower() == (item.get("expected_frequency") or "").lower()
                )
                if row["units_match"] is False:
                    print(f"         !! 단위 불일치 - 기대 {item.get('expected_units')}")
                if not row["meta_freq_match"]:
                    print(f"         !! 주기 불일치 - 기대 {item.get('expected_frequency')}")
            if not row.get("ok"):
                print(f"         {row.get('error')}")
            time.sleep(CALL_DELAY_SEC)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    ok_count = sum(1 for r in results if r.get("ok"))
    print(f"\n성공 {ok_count} / {len(results)}")
    print(f"리포트: {REPORT}")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
