"""MQWAY 게시용 HTML 데모 생성.

store.py / export.py 가 아직 없으므로 FRED 에서 직접 받아 스냅샷을 만들고
render.render_post() 에 넘긴다. 파이프라인이 완성되면 이 스크립트는
DB 에서 읽도록 바뀌고 render_post() 는 그대로 쓴다.

생성 후 MQWAY 제약을 검사한다.
  - 본문 64KB 미만
  - 최상단 텍스트 요약 문단 존재
  - strip_tags() 미리보기가 비지 않음
  - 게시 금지 시리즈가 본문에 없음
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from liquidity_feed.render import DISCLAIMER, render_post  # noqa: E402

API = "https://api.stlouisfed.org/fred"
OUT = ROOT / "data" / "export" / "post.html"
LATEST = ROOT / "data" / "export" / "latest.json"
WEEKS = 104  # 차트에 싣는 주간 관측치 수. 본문 크기와 직결된다.
CALL_DELAY_SEC = 0.4

M_TO_T = 1e6  # Millions -> 조
B_TO_T = 1e3  # Billions -> 조


def get(client: httpx.Client, path: str, **params) -> dict:
    params.update({"api_key": os.environ["FRED_API_KEY"], "file_type": "json"})
    resp = client.get(f"{API}/{path}", params=params, timeout=60.0)
    resp.raise_for_status()
    time.sleep(CALL_DELAY_SEC)
    return resp.json()


def observations(client: httpx.Client, sid: str) -> dict[date, float]:
    """결측치를 뺀 관측치만 돌려준다. FRED 는 결측을 '.' 로 준다."""
    payload = get(client, "series/observations", series_id=sid)
    return {
        date.fromisoformat(o["date"]): float(o["value"])
        for o in payload["observations"]
        if o["value"] != "."
    }


def pct_change(series: dict[date, float], as_of: date, days: int) -> float | None:
    """as_of 기준 days 일 전 대비 변화율. 그 이전 관측치 중 가장 가까운 값을 쓴다."""
    if as_of not in series:
        return None
    target = date.fromordinal(as_of.toordinal() - days)
    earlier = [d for d in series if d <= target]
    if not earlier:
        return None
    base = series[max(earlier)]
    if base == 0:
        return None
    return (series[as_of] / base - 1) * 100


def abs_change(series: dict[date, float], as_of: date, days: int, scale: float) -> float | None:
    """as_of 기준 days 일 전 대비 절대 변화량. 변화율이 의미 없을 때 쓴다."""
    if as_of not in series:
        return None
    target = date.fromordinal(as_of.toordinal() - days)
    earlier = [d for d in series if d <= target]
    if not earlier:
        return None
    return (series[as_of] - series[max(earlier)]) / scale


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if not os.environ.get("FRED_API_KEY", "").strip():
        print("FRED_API_KEY 가 없다. .env 를 확인한다.")
        return 2

    cfg = yaml.safe_load((ROOT / "config" / "series.yaml").read_text(encoding="utf-8"))
    blocked = {b["id"] for b in cfg["blocked"]}

    # 게시물 문구는 코드가 아니라 설정에서 온다
    thr = yaml.safe_load((ROOT / "config" / "thresholds.yaml").read_text(encoding="utf-8"))
    labels = thr.get("metrics", {})
    series_terms = thr.get("series", {})

    need = [
        "WALCL", "WDTGAL", "RRPONTSYD", "WRESBAL", "WRBWFRBL", "WTREGEN",
        "WSHOSHO", "WSHOTSL", "WSHOMCB", "GDP", "TOTLL", "DPSACBW027SBOG",
        "M2SL", "STLFSI4", "NFCI", "SOFR", "EFFR", "DTB4WK", "MMMFFAQ027S",
    ]
    assert not (set(need) & blocked), "게시 금지 시리즈가 수집 목록에 있다"

    print(f"FRED 에서 {len(need)}개 시리즈를 받는다...")
    with httpx.Client(headers={"User-Agent": "liquidity-feed/0.1 demo"}) as client:
        data = {sid: observations(client, sid) for sid in need}

        # 출처는 릴리스 단위로 캐시해서 중복 호출을 줄인다
        print("출처 기관 메타를 받는다...")
        sources: dict[int, dict] = {}
        for sid in ("WALCL", "TOTLL", "GDP", "NFCI", "STLFSI4", "SOFR", "MMMFFAQ027S"):
            rel = get(client, "series/release", series_id=sid)["releases"][0]
            if rel["id"] in sources:
                continue
            org = get(client, "release/sources", release_id=rel["id"])["sources"][0]
            sources[rel["id"]] = {"name": org["name"], "release": rel["name"]}

    # 수요일 그리드. net_liquidity 구성요소가 전부 값을 가진 날짜만 쓴다.
    wednesdays = sorted(
        d for d in data["WALCL"]
        if d in data["WDTGAL"] and d in data["RRPONTSYD"] and d in data["WSHOTSL"]
    )[-WEEKS:]
    as_of = wednesdays[-1]
    print(f"차트 구간 {wednesdays[0]} ~ {as_of} ({len(wednesdays)}주)")

    def net_liq(d: date) -> float:
        return data["WALCL"][d] / M_TO_T - data["WDTGAL"][d] / M_TO_T - data["RRPONTSYD"][d] / B_TO_T

    charts = {
        "dates": [d.isoformat() for d in wednesdays],
        "net_liquidity": [round(net_liq(d), 4) for d in wednesdays],
        "treasuries": [round(data["WSHOTSL"][d] / M_TO_T, 4) for d in wednesdays],
        "mbs": [round(data["WSHOMCB"][d] / M_TO_T, 4) for d in wednesdays],
        "other": [
            round((data["WALCL"][d] - data["WSHOTSL"][d] - data["WSHOMCB"][d]) / M_TO_T, 4)
            for d in wednesdays
        ],
    }

    gdp_as_of = max(data["GDP"])
    bank_as_of = max(set(data["TOTLL"]) & set(data["DPSACBW027SBOG"]))
    net_liq_series = {
        d: net_liq(d)
        for d in sorted(data["WALCL"])
        if d in data["WDTGAL"] and d in data["RRPONTSYD"]
    }

    derived = {
        "net_liquidity": net_liq(as_of),
        "net_liquidity_delta_week": pct_change(net_liq_series, as_of, 7),
        "net_liquidity_delta_week_abs": abs_change(net_liq_series, as_of, 7, 1.0),
        "reserves": data["WRESBAL"][as_of] / M_TO_T,
        "reserves_delta_week": pct_change(data["WRESBAL"], as_of, 7),
        "reserves_delta_week_abs": abs_change(data["WRESBAL"], as_of, 7, M_TO_T),
        "tga": data["WDTGAL"][as_of] / M_TO_T,
        "tga_delta_week": pct_change(data["WDTGAL"], as_of, 7),
        "tga_delta_week_abs": abs_change(data["WDTGAL"], as_of, 7, M_TO_T),
        "rrp": data["RRPONTSYD"][as_of] / B_TO_T,
        "rrp_delta_week": pct_change(data["RRPONTSYD"], as_of, 7),
        # 역레포는 잔액이 0 에 가까워 변화율이 의미를 잃는다.
        # 분모가 작을 때는 절대 변화량으로 보여준다.
        "rrp_delta_week_abs": abs_change(data["RRPONTSYD"], as_of, 7, B_TO_T),
        "total_assets": data["WALCL"][as_of] / M_TO_T,
        "treasuries": data["WSHOTSL"][as_of] / M_TO_T,
        "mbs": data["WSHOMCB"][as_of] / M_TO_T,
        "other_assets": (
            data["WALCL"][as_of] - data["WSHOTSL"][as_of] - data["WSHOMCB"][as_of]
        ) / M_TO_T,
        "reserves_to_gdp": (data["WRESBAL"][as_of] / M_TO_T) / (data["GDP"][gdp_as_of] / B_TO_T) * 100,
        "loan_to_deposit": data["TOTLL"][bank_as_of] / data["DPSACBW027SBOG"][bank_as_of] * 100,
        "gdp_as_of": gdp_as_of.isoformat(),
        "bank_as_of": bank_as_of.isoformat(),
    }

    def row(sid: str, name: str, to_t: float | None, unit: str = "조",
            on: date | None = None) -> dict:
        """표 한 행. on 을 주면 그 날짜 값을 쓴다.

        역레포는 일간이라 최신값이 수요일 값과 다르다. 위쪽 타일과
        순유동성 계산이 수요일 기준이므로 표도 같은 날짜로 맞춘다.
        맞추지 않으면 같은 지표가 한 게시물에 두 값으로 나온다.
        """
        info = series_terms.get(sid, {})
        name = info.get("term", name)
        s = data[sid]
        d = on if on is not None and on in s else max(s)
        raw = s[d]
        display = f"{raw / to_t:,.3f}{unit}" if to_t else f"{raw:,.2f}{unit}"
        return {
            "series_id": sid,
            "name_ko": name,
            "display": display,
            "delta_week": pct_change(s, d, 7),
            "delta_month": pct_change(s, d, 30),
            "as_of": d.isoformat(),
            "gloss": info.get("gloss", ""),
        }

    layers = [
        row("WRESBAL", "지급준비금 (주간평균)", M_TO_T),
        row("WRBWFRBL", "지급준비금 (수요일)", M_TO_T),
        row("WDTGAL", "재무부 일반계정", M_TO_T),
        row("RRPONTSYD", "익일물 역레포", B_TO_T, on=as_of),
        row("WALCL", "연준 총자산", M_TO_T),
        row("WSHOTSL", "연준 보유 국채", M_TO_T),
        row("WSHOMCB", "연준 보유 MBS", M_TO_T),
        row("M2SL", "M2 통화량", B_TO_T),
        row("TOTLL", "은행 총대출", B_TO_T),
        row("DPSACBW027SBOG", "은행 예금", B_TO_T),
        row("MMMFFAQ027S", "MMF 총자산", M_TO_T),
        row("STLFSI4", "세인트루이스 금융스트레스지수", None, ""),
        row("NFCI", "시카고 전미금융여건지수", None, ""),
        row("SOFR", "SOFR", None, "%"),
        row("EFFR", "실효 연방기금금리", None, "%"),
        row("DTB4WK", "4주물 국채 수익률", None, "%"),
    ]

    snapshot = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "as_of_label": as_of.isoformat(),
            "disclaimer": DISCLAIMER,
            "sources": sorted(sources.values(), key=lambda s: s["name"]),
        },
        "derived": derived,
        "layers": layers,
        "charts": charts,
        "labels": labels,
    }

    body = render_post(snapshot)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")

    # latest.json 은 게시물과 별개 산출물이다. charts 와 labels 는 게시물
    # 전용이라 빼고, 시리즈별 출처 기관은 여기에 전부 싣는다(법적 의무 3).
    latest = {
        "meta": snapshot["meta"],
        "layers": snapshot["layers"],
        "derived": snapshot["derived"],
    }
    LATEST.write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- MQWAY 제약 검사 ---
    size = len(body.encode("utf-8"))
    preview = re.sub(r"<(script|style)[^>]*>.*?</>", " ", body, flags=re.S)
    preview = re.sub(r"<[^>]+>", " ", preview).strip()
    preview = re.sub(r"\s+", " ", preview)[:200]
    lede_ok = body.index('class="lf-sum"') < body.index("lf-chart")
    no_blocked = not any(b in body for b in blocked)

    print()
    print("=" * 70)
    print("MQWAY 제약 검사")
    print("=" * 70)
    checks = [
        (f"본문 64KB 미만 (실제 {size:,} bytes, 여유 {65536 - size:,})", size < 65536),
        ("최상단에 개조식 텍스트 요약이 있다", lede_ok),
        ("strip_tags 미리보기가 비지 않는다", len(preview) > 50),
        ("게시 금지 시리즈가 본문에 없다", no_blocked),
        ("FRED 면책 문구가 들어 있다", DISCLAIMER in body),
        ("ECharts 5.4.3 을 직접 불러온다", "echarts@5.4.3" in body),
        # 본문 출처는 FRED 한 줄로 줄였다. 시리즈별 기관과 인용 정보는
        # latest.json 의 meta.sources 가 담당한다(법적 의무 3).
        ("본문 출처가 FRED 한 줄이다", "<p>출처 FRED</p>" in body),
        ("기관 정보가 스냅샷 meta.sources 에 있다", len(snapshot["meta"]["sources"]) > 0),
    ]
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    print()
    print("미리보기 첫 200자:")
    print(f"  {preview}")
    print()
    print(f"산출물: {OUT}")
    print(f"        {LATEST}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
