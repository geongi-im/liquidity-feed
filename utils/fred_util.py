"""FRED 수집과 파생 지표 계산.

FRED 는 호출마다 전체 히스토리를 주므로 증분 저장소가 필요 없다.
받은 관측치를 메모리에서 바로 파생 지표로 바꾸고 스냅샷 dict 로 넘긴다.
그 구조가 RenderUtil.render_post() 의 입력이자 latest.json 의 내용이다.

단위 환산은 시리즈마다 다르다. 연준 대차대조표 계열은 Millions,
역레포와 GDP 계열은 Billions 로 온다. 둘을 섞으면 순유동성이 1000배
어긋나므로 M_TO_T / B_TO_T 를 반드시 구분해서 쓴다.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime

import httpx

from utils.config_util import blocked_ids, env, load_series, load_thresholds
from utils.logger_util import LoggerUtil
from utils.render_util import DISCLAIMER

API = "https://api.stlouisfed.org/fred"

WEEKS = 104  # 차트에 싣는 주간 관측치 수. 본문 크기와 직결된다.
CALL_DELAY_SEC = 0.4
TIMEOUT_SEC = 60.0

M_TO_T = 1e6  # Millions -> 조
B_TO_T = 1e3  # Billions -> 조

# 게시물 한 장에 필요한 시리즈. config/series.yaml 의 전체 목록 중
# 지금 본문과 차트가 실제로 쓰는 것만 받는다.
NEEDED = (
    "WALCL", "WDTGAL", "RRPONTSYD", "WRESBAL", "WRBWFRBL", "WTREGEN",
    "WSHOSHO", "WSHOTSL", "WSHOMCB", "GDP", "TOTLL", "DPSACBW027SBOG",
    "M2SL", "STLFSI4", "NFCI", "SOFR", "EFFR", "DTB4WK", "MMMFFAQ027S",
)

# 출처 기관을 확인할 대표 시리즈. 릴리스 단위로 캐시해 중복 호출을 줄인다.
SOURCE_PROBES = ("WALCL", "TOTLL", "GDP", "NFCI", "STLFSI4", "SOFR", "MMMFFAQ027S")

# 표에 싣는 행. (시리즈 ID, 기본 이름, 환산 단위, 표기 단위)
TABLE_ROWS = (
    ("WRESBAL", "지급준비금 (주간평균)", M_TO_T, "조"),
    ("WRBWFRBL", "지급준비금 (수요일)", M_TO_T, "조"),
    ("WDTGAL", "재무부 일반계정", M_TO_T, "조"),
    ("RRPONTSYD", "익일물 역레포", B_TO_T, "조"),
    ("WALCL", "연준 총자산", M_TO_T, "조"),
    ("WSHOTSL", "연준 보유 국채", M_TO_T, "조"),
    ("WSHOMCB", "연준 보유 MBS", M_TO_T, "조"),
    ("M2SL", "M2 통화량", B_TO_T, "조"),
    ("TOTLL", "은행 총대출", B_TO_T, "조"),
    ("DPSACBW027SBOG", "은행 예금", B_TO_T, "조"),
    ("MMMFFAQ027S", "MMF 총자산", M_TO_T, "조"),
    ("STLFSI4", "세인트루이스 금융스트레스지수", None, ""),
    ("NFCI", "시카고 전미금융여건지수", None, ""),
    ("SOFR", "SOFR", None, "%"),
    ("EFFR", "실효 연방기금금리", None, "%"),
    ("DTB4WK", "4주물 국채 수익률", None, "%"),
)

# 역레포는 일간이라 최신값이 수요일 값과 다르다. 위쪽 타일과 순유동성
# 계산이 수요일 기준이므로 표도 같은 날짜로 맞춘다. 맞추지 않으면
# 같은 지표가 한 게시물에 두 값으로 나온다.
PIN_TO_AS_OF = ("RRPONTSYD",)


class FredError(RuntimeError):
    """수집 실패. 파이프라인을 여기서 멈춘다."""


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


def abs_change(
    series: dict[date, float], as_of: date, days: int, scale: float
) -> float | None:
    """as_of 기준 days 일 전 대비 절대 변화량. 변화율이 의미 없을 때 쓴다."""
    if as_of not in series:
        return None
    target = date.fromordinal(as_of.toordinal() - days)
    earlier = [d for d in series if d <= target]
    if not earlier:
        return None
    return (series[as_of] - series[max(earlier)]) / scale


class FredUtil:
    def __init__(self):
        self.logger = LoggerUtil().get_logger()

    def _get(self, client: httpx.Client, path: str, **params) -> dict:
        params.update({"api_key": env("FRED_API_KEY"), "file_type": "json"})
        resp = client.get(f"{API}/{path}", params=params, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        time.sleep(CALL_DELAY_SEC)
        return resp.json()

    def _observations(self, client: httpx.Client, sid: str) -> dict[date, float]:
        """결측치를 뺀 관측치만 돌려준다. FRED 는 결측을 '.' 로 준다."""
        payload = self._get(client, "series/observations", series_id=sid)
        return {
            date.fromisoformat(o["date"]): float(o["value"])
            for o in payload["observations"]
            if o["value"] != "."
        }

    def collect(self) -> tuple[dict[str, dict[date, float]], list[dict]]:
        """시리즈 관측치와 출처 기관 정보를 받는다."""
        if not env("FRED_API_KEY"):
            raise FredError("FRED_API_KEY 가 없다. .env 를 확인한다")

        blocked = blocked_ids()
        if set(NEEDED) & blocked:
            raise FredError(f"게시 금지 시리즈가 수집 목록에 있다: {set(NEEDED) & blocked}")

        # config/series.yaml 에 없는 ID 를 받아오면 문서와 코드가 어긋난다
        declared = {s["id"] for s in load_series()["series"]}
        unknown = set(NEEDED) - declared
        if unknown:
            raise FredError(f"config/series.yaml 에 없는 시리즈를 받으려 한다: {unknown}")

        self.logger.info(f"FRED 에서 {len(NEEDED)}개 시리즈를 받는다...")
        with httpx.Client(headers={"User-Agent": "liquidity-feed/0.1"}) as client:
            data = {sid: self._observations(client, sid) for sid in NEEDED}

            self.logger.info("출처 기관 메타를 받는다...")
            sources: dict[int, dict] = {}
            for sid in SOURCE_PROBES:
                rel = self._get(client, "series/release", series_id=sid)["releases"][0]
                if rel["id"] in sources:
                    continue
                org = self._get(client, "release/sources", release_id=rel["id"])["sources"][0]
                sources[rel["id"]] = {"name": org["name"], "release": rel["name"]}

        return data, sorted(sources.values(), key=lambda s: s["name"])

    def build_snapshot(self, data: dict[str, dict[date, float]], sources: list[dict]) -> dict:
        """관측치를 게시물 스냅샷으로 만든다.

        수요일 그리드를 기준으로 삼는다. 순유동성 구성요소가 전부 값을
        가진 날짜만 써야 합이 어긋나지 않는다.
        """
        thr = load_thresholds()
        labels = thr.get("metrics", {})
        series_terms = thr.get("series", {})

        wednesdays = sorted(
            d for d in data["WALCL"]
            if d in data["WDTGAL"] and d in data["RRPONTSYD"] and d in data["WSHOTSL"]
        )[-WEEKS:]
        if not wednesdays:
            raise FredError("순유동성 구성요소가 겹치는 날짜가 없다")
        as_of = wednesdays[-1]
        self.logger.info(f"차트 구간 {wednesdays[0]} ~ {as_of} ({len(wednesdays)}주)")

        def net_liq(d: date) -> float:
            return (
                data["WALCL"][d] / M_TO_T
                - data["WDTGAL"][d] / M_TO_T
                - data["RRPONTSYD"][d] / B_TO_T
            )

        charts = {
            "dates": [d.isoformat() for d in wednesdays],
            "net_liquidity": [round(net_liq(d), 4) for d in wednesdays],
            "treasuries": [round(data["WSHOTSL"][d] / M_TO_T, 4) for d in wednesdays],
            "mbs": [round(data["WSHOMCB"][d] / M_TO_T, 4) for d in wednesdays],
            "other": [
                round(
                    (data["WALCL"][d] - data["WSHOTSL"][d] - data["WSHOMCB"][d]) / M_TO_T, 4
                )
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
            "reserves_to_gdp": (
                (data["WRESBAL"][as_of] / M_TO_T) / (data["GDP"][gdp_as_of] / B_TO_T) * 100
            ),
            "loan_to_deposit": (
                data["TOTLL"][bank_as_of] / data["DPSACBW027SBOG"][bank_as_of] * 100
            ),
            "gdp_as_of": gdp_as_of.isoformat(),
            "bank_as_of": bank_as_of.isoformat(),
        }

        layers = [
            self._row(data, series_terms, sid, name, to_t, unit, as_of)
            for sid, name, to_t, unit in TABLE_ROWS
        ]

        return {
            "meta": {
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
                "as_of_label": as_of.isoformat(),
                "disclaimer": DISCLAIMER,
                "sources": sources,
            },
            "derived": derived,
            "layers": layers,
            "charts": charts,
            "labels": labels,
        }

    @staticmethod
    def _row(
        data: dict[str, dict[date, float]],
        series_terms: dict,
        sid: str,
        name: str,
        to_t: float | None,
        unit: str,
        as_of: date,
    ) -> dict:
        """표 한 행. PIN_TO_AS_OF 에 든 시리즈는 수요일 값으로 맞춘다."""
        info = series_terms.get(sid, {})
        name = info.get("term", name)
        s = data[sid]
        pin = as_of if sid in PIN_TO_AS_OF else None
        d = pin if pin is not None and pin in s else max(s)
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
