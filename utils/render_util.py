"""MQWAY 게시용 HTML 본문 생성.

MQWAY 제약 때문에 지켜야 하는 것들:
  - 본문 최상단에 텍스트 요약을 둔다. 게시판 목록이 strip_tags() 로
    미리보기를 만들기 때문에 차트만 있으면 미리보기가 빈다.
  - mq_content 가 MySQL text 라 64KB 가 상한이다. render_post() 는
    문자열만 돌려주고 호출부가 크기를 검사한다.
  - 게시판 상세 화면에는 ECharts 가 로드돼 있지 않다. 본문 안에서 직접
    불러온다. MQWAY 메인이 쓰는 5.4.3 에 맞춘다.
  - 본문은 MQWAY 페이지에 이스케이프 없이 그대로 삽입된다. CSS 가 바깥
    레이아웃을 건드리지 않도록 모든 선택자를 .lf-root 아래로 한정한다.

MQWAY 사이트 톤에 맞춘 부분 (mqway.com tailwind.config 에서 확인한 값):
  - 라이트 전용. MQWAY 에는 다크모드가 없다(prefers-color-scheme 0건).
    본문이 OS 설정을 따라 어두워지면 흰 페이지 위에 검은 블록이 떠버린다.
  - 배경 #F8F9FA, 카드 #FFFFFF, 테두리 #e5e7eb, 잉크 #2D3047
  - 액센트 #FF4D4D, 서체 Noto Sans KR / Outfit (MQWAY 가 이미 로드한다)

차트 색은 MQWAY 브랜드 색조를 유지한 채 밝기와 채도만 접근성 통과
구간으로 스냅한 값이다. 브랜드 원색은 너무 밝아 검증을 통과하지 못한다.
  코랄 #FF4D4D -> #EB383D    민트 #4ECDC4 -> #009D94    앰버 #FFB347 -> #BA7500
순서가 안전장치다. 코랄과 앰버를 붙이면 deutan 분리도가 2.4 로 떨어지므로
반드시 민트를 사이에 둔다.

용어는 정식 명칭을 그대로 쓰고, 설명이 필요한 것에는 물음표 버튼을 붙여
툴팁으로 보여준다. 문구는 이 파일에 없다. config/thresholds.yaml 에 있고
스냅샷에 실려 들어온다. 표현을 고치려면 그 파일만 고친다.

법적 의무:
  - FRED 면책 문구를 하단에 항상 넣는다.
  - 본문 출처 표기는 FRED 한 줄. 시리즈별 기관과 인용 정보는
    latest.json 의 meta.sources 가 담당한다.
  - 연준 로고나 상표는 쓰지 않는다.
"""

from __future__ import annotations

import html
import json

ECHARTS_SRC = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"

DISCLAIMER = (
    "This product uses the FRED(R) API but is not endorsed or certified "
    "by the Federal Reserve Bank of St. Louis."
)

# 차트 계열색. 라이트 서피스 #FFFFFF 기준으로 검증 통과한 순서다.
SERIES_COLORS = ("#EB383D", "#009D94", "#BA7500")

# 변화율이 이 값을 넘으면 분모가 너무 작아 뜻을 잃는다고 보고 금액만 쓴다.
PCT_NOISE_LIMIT = 100.0

STYLE = """
.lf-root{--lf-plane:#F8F9FA;--lf-surface:#FFFFFF;--lf-line:#e5e7eb;
--lf-ink:#2D3047;--lf-ink2:#3D4148;--lf-muted:#6B7280;--lf-accent:#FF4D4D;
--lf-s1:#EB383D;--lf-s2:#009D94;--lf-s3:#BA7500;
background:var(--lf-plane);color:var(--lf-ink);
font-family:'Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif;
line-height:1.6;padding:22px 18px;border-radius:10px}
.lf-root *{box-sizing:border-box}
.lf-sum{margin:0 0 20px;padding:0;list-style:none}
.lf-sum li{font-size:15px;color:var(--lf-ink);margin:0 0 6px;padding-left:14px;
position:relative}
.lf-sum li:first-child{font-weight:600}
.lf-sum li:before{content:"-";position:absolute;left:0;color:var(--lf-accent);
font-weight:700}
.lf-term{position:relative;display:inline-flex;align-items:center;gap:4px;
vertical-align:baseline}
.lf-help{appearance:none;-webkit-appearance:none;flex:none;
width:15px;height:15px;padding:0;border-radius:50%;cursor:pointer;
border:1px solid var(--lf-line);background:var(--lf-plane);color:var(--lf-muted);
font:600 10px/1 'Noto Sans KR',sans-serif}
.lf-help:hover{border-color:var(--lf-accent);color:var(--lf-accent)}
.lf-help:focus-visible{outline:2px solid var(--lf-accent);outline-offset:1px}
.lf-tip{position:absolute;left:0;top:calc(100% + 6px);z-index:20;
width:max-content;max-width:230px;padding:8px 10px;border-radius:6px;
background:var(--lf-ink);color:#fff;text-align:left;white-space:normal;
font:400 11.5px/1.55 'Noto Sans KR',sans-serif;
box-shadow:0 3px 10px rgba(45,48,71,.22);
visibility:hidden;opacity:0;pointer-events:none;transition:opacity .12s}
.lf-term.lf-flip .lf-tip{left:auto;right:0}
.lf-term.lf-open .lf-tip{visibility:visible;opacity:1;pointer-events:auto}
@media (hover:hover){.lf-term:hover .lf-tip{visibility:visible;opacity:1}}
.lf-tip b{display:block;font-weight:600;margin:0 0 2px}
@media (prefers-reduced-motion:reduce){.lf-tip{transition:none}}
.lf-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(156px,1fr));
gap:9px;margin:0 0 22px}
.lf-tile{background:var(--lf-surface);border:1px solid var(--lf-line);
border-radius:8px;padding:11px 13px}
.lf-tile-k{font-size:12.5px;color:var(--lf-ink2);margin:0 0 6px;font-weight:500}
.lf-tile-v{font-size:23px;font-weight:600;color:var(--lf-ink);margin:0;
font-family:'Outfit','Noto Sans KR',sans-serif}
.lf-tile-d{font-size:12px;color:var(--lf-ink2);margin:3px 0 0;
font-variant-numeric:tabular-nums}
.lf-fig{background:var(--lf-surface);border:1px solid var(--lf-line);
border-radius:8px;padding:14px;margin:0 0 18px}
.lf-fig h3{font-size:15px;font-weight:600;color:var(--lf-ink);margin:0 0 4px}
.lf-fig .lf-spec{font-size:12px;color:var(--lf-muted);margin:0 0 12px}
.lf-chart{width:100%;height:270px}
.lf-legend{display:flex;flex-wrap:wrap;gap:13px;margin:9px 0 0;
font-size:12px;color:var(--lf-ink2)}
.lf-legend span{display:inline-flex;align-items:center;gap:6px}
.lf-dot{width:9px;height:9px;border-radius:2px;display:inline-block}
.lf-tbl{width:100%;border-collapse:collapse;font-size:13px;
background:var(--lf-surface);border:1px solid var(--lf-line);border-radius:8px}
.lf-tbl caption{font-size:15px;font-weight:600;color:var(--lf-ink);
text-align:left;padding:12px 13px 7px}
.lf-tbl th,.lf-tbl td{padding:7px 13px;border-top:1px solid var(--lf-line);
text-align:right;font-variant-numeric:tabular-nums;color:var(--lf-ink)}
.lf-tbl th{color:var(--lf-muted);font-weight:500;font-size:12px}
.lf-tbl th:first-child,.lf-tbl td:first-child{text-align:left;
font-variant-numeric:normal}
.lf-tbl .lf-sub{display:block;color:var(--lf-muted);font-size:11px}
.lf-foot{margin:18px 0 0;padding:12px 0 0;border-top:1px solid var(--lf-line);
font-size:11.5px;color:var(--lf-muted);line-height:1.55}
.lf-foot p{margin:0 0 3px}
.lf-noscript{font-size:12px;color:var(--lf-ink2);padding:8px 0}
"""


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _fmt_trillion(value: float | None, digits: int = 3) -> str:
    """조 달러 표기."""
    if value is None:
        return "자료 없음"
    return f"{value:,.{digits}f}조"


def _fmt_delta(pct: float | None) -> str:
    """변화율 표기. 방향은 부호로 나타내고 색으로 구분하지 않는다."""
    if pct is None:
        return "-"
    return f"{pct:+.2f}%"


def _fmt_change(abs_value: float | None, pct: float | None) -> str:
    """주간 변화 표기. 금액을 앞세우고 변화율을 괄호에 붙인다.

    잔액이 0 에 가까우면 변화율이 수백 퍼센트로 튀어 뜻을 잃으므로
    그럴 때는 금액만 쓴다.
    """
    if abs_value is None:
        return _fmt_delta(pct)
    amount = f"{abs_value:+,.3f}조"
    if pct is None or abs(pct) > PCT_NOISE_LIMIT:
        return amount
    return f"{amount} ({pct:+.2f}%)"


def _direction(value: float | None, unit: str = "조 달러") -> str:
    """변화 방향을 우리말로. 좋다/나쁘다 판단은 하지 않는다."""
    if value is None:
        return "변화 자료 없음"
    if abs(value) < 0.0005:
        return "한 주 전과 거의 같다"
    verb = "늘었다" if value > 0 else "줄었다"
    return f"한 주 전보다 {abs(value):,.3f}{unit} {verb}"


def _term(label: str, plain: str = "", gloss: str = "") -> str:
    """용어 표기. 해설이 있으면 물음표 버튼과 툴팁을 붙인다.

    해설이 없으면 버튼 없이 글자만 돌려준다.
    """
    text = _esc(label)
    if not gloss:
        return text
    lead = f"<b>{_esc(plain)}</b>" if plain else ""
    return (
        f'<span class="lf-term">{text}'
        f'<button type="button" class="lf-help" aria-expanded="false" '
        f'aria-label="{text} 설명 보기">?</button>'
        f'<span class="lf-tip" role="tooltip">{lead}{_esc(gloss)}</span>'
        "</span>"
    )


def _tile(label_html: str, value: str, sub: str) -> str:
    return (
        '<div class="lf-tile">'
        f'<p class="lf-tile-k">{label_html}</p>'
        f'<p class="lf-tile-v">{_esc(value)}</p>'
        f'<p class="lf-tile-d">{_esc(sub)}</p>'
        "</div>"
    )


def post_title(as_of_label: str) -> str:
    """게시글 제목. 문서 제목과 알림 제목이 갈라지지 않도록 한 곳에서 만든다."""
    return f"{as_of_label} 미국 유동성 지표 주간 브리핑"


def build_notify_facts(derived: dict) -> list[str]:
    """텔레그램 알림에 싣는 핵심 수치. 개조식으로 짧게 유지한다.

    게시물 본문 요약과 용도가 다르다. 본문은 읽는 글이고 알림은 훑는
    것이라, 문장이 아니라 "키: 값" 세 줄로 끝낸다.
    """
    net = _fmt_trillion(derived["net_liquidity"])
    net_chg = derived.get("net_liquidity_delta_week_abs")
    chg = f" (주간 {net_chg:+,.3f}조)" if net_chg is not None else ""
    return [
        f"순유동성: {net}{chg}",
        f"지급준비금: {_fmt_trillion(derived['reserves'])} "
        f"(GDP 대비 {derived['reserves_to_gdp']:.2f}%)",
        f"연준 총자산: {_fmt_trillion(derived['total_assets'])}",
    ]


def build_summary(derived: dict, labels: dict, as_of_label: str) -> list[str]:
    """개조식 요약. 게시판 목록 미리보기가 이 문장들을 이어붙여 쓴다."""

    def term(key: str) -> str:
        return labels.get(key, {}).get("term", key)

    return [
        f"{as_of_label} 기준 미국 유동성 요약",
        f"{term('net_liquidity')} {_fmt_trillion(derived['net_liquidity'])} 달러, "
        f"{_direction(derived['net_liquidity_delta_week_abs'])}",
        f"{term('reserves')} {_fmt_trillion(derived['reserves'])} 달러, "
        f"명목 GDP 대비 {derived['reserves_to_gdp']:.2f}%",
        f"{term('total_assets')} {_fmt_trillion(derived['total_assets'])} 달러 "
        f"= 국채 {_fmt_trillion(derived['treasuries'])} "
        f"+ MBS {_fmt_trillion(derived['mbs'])} "
        f"+ 기타 {_fmt_trillion(derived['other_assets'])}",
        f"{term('loan_to_deposit')} {derived['loan_to_deposit']:.2f}%",
    ]


def render_post(snapshot: dict) -> str:
    """스냅샷 dict 를 MQWAY 본문 HTML 로 만든다.

    snapshot 구조는 output/export/latest.json 과 같고 charts 와 labels 키가
    게시물용으로 추가된다. labels 는 config/thresholds.yaml 에서 온다.
    FredUtil.build_snapshot() 이 만든 것을 그대로 받는다.
    """
    meta = snapshot["meta"]
    derived = snapshot["derived"]
    layers = snapshot["layers"]
    charts = snapshot["charts"]
    labels = snapshot["labels"]

    def metric_term(key: str) -> str:
        item = labels.get(key, {})
        return _term(item.get("term", key), item.get("plain", ""), item.get("gloss", ""))

    def change(key: str) -> str:
        return "주간 " + _fmt_change(
            derived.get(f"{key}_delta_week_abs"), derived.get(f"{key}_delta_week")
        )

    summary = "".join(
        f"<li>{_esc(line)}</li>"
        for line in build_summary(derived, labels, meta["as_of_label"])
    )

    tiles = "".join([
        _tile(metric_term("net_liquidity"),
              _fmt_trillion(derived["net_liquidity"]), change("net_liquidity")),
        _tile(metric_term("reserves"),
              _fmt_trillion(derived["reserves"]), change("reserves")),
        _tile(metric_term("tga"),
              _fmt_trillion(derived["tga"]), change("tga")),
        _tile(metric_term("rrp"),
              _fmt_trillion(derived["rrp"]), change("rrp")),
        _tile(metric_term("reserves_to_gdp"),
              f"{derived['reserves_to_gdp']:.2f}%", f"GDP {derived['gdp_as_of']} 연율"),
        _tile(metric_term("loan_to_deposit"),
              f"{derived['loan_to_deposit']:.2f}%", f"기준일 {derived['bank_as_of']}"),
    ])

    rows = "".join(
        "<tr>"
        f'<td>{_term(r["name_ko"], "", r.get("gloss", ""))}'
        f'<span class="lf-sub">{_esc(r["series_id"])}</span></td>'
        f'<td>{_esc(r["display"])}</td>'
        f'<td>{_esc(_fmt_delta(r["delta_week"]))}</td>'
        f'<td>{_esc(_fmt_delta(r["delta_month"]))}</td>'
        f'<td class="lf-sub">{_esc(r["as_of"])}</td>'
        "</tr>"
        for r in layers
    )

    weeks = len(charts["dates"])
    spec_netliq = (
        "연준 총자산 - 재무부 일반계정 - 익일물 역레포 / "
        f"수요일 시점값 / 단위 조 달러 / 최근 {weeks}주"
    )
    spec_balance = (
        f"보유 자산 분해 / 수요일 시점값 / 단위 조 달러 / 최근 {weeks}주"
    )
    payload = json.dumps(charts, ensure_ascii=False, separators=(",", ":"))
    s1, s2, s3 = SERIES_COLORS

    return f"""<div class="lf-root">
<ul class="lf-sum">{summary}</ul>
<div class="lf-kpi">{tiles}</div>
<div class="lf-fig">
<h3>순유동성 추이</h3>
<p class="lf-spec">{spec_netliq}</p>
<div class="lf-chart" id="lfNetLiq"></div>
<noscript><p class="lf-noscript">차트는 자바스크립트가 필요하다. 수치는 아래 표 참조.</p></noscript>
</div>
<div class="lf-fig">
<h3>연준 대차대조표 구성</h3>
<p class="lf-spec">{spec_balance}</p>
<div class="lf-chart" id="lfBalance"></div>
<div class="lf-legend">
<span><i class="lf-dot" style="background:{s1}"></i>국채</span>
<span><i class="lf-dot" style="background:{s2}"></i>MBS</span>
<span><i class="lf-dot" style="background:{s3}"></i>기타</span>
</div>
<noscript><p class="lf-noscript">차트는 자바스크립트가 필요하다. 수치는 아래 표 참조.</p></noscript>
</div>
<table class="lf-tbl">
<caption>지표별 최신값</caption>
<thead><tr><th>지표</th><th>값</th><th>주간</th><th>월간</th><th>기준일</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<div class="lf-foot">
<p>출처 FRED</p>
<p>{_esc(DISCLAIMER)}</p>
</div>
</div>
<style>{STYLE}</style>
<script>
(function(){{
var root=document.querySelector(".lf-root");
if(!root)return;

// --- 용어 툴팁 ---
// 툴팁은 늘 배치돼 있고 보이기만 감춘다. 그래야 위치를 미리 재서
// 오른쪽 끝에서 페이지 밖으로 삐져나가는 것을 막을 수 있다.
function flip(){{
var box=root.getBoundingClientRect();
var terms=root.querySelectorAll(".lf-term");
for(var i=0;i<terms.length;i++){{
var t=terms[i];
t.classList.remove("lf-flip");
var tip=t.querySelector(".lf-tip");
if(tip&&tip.getBoundingClientRect().right>box.right-4)t.classList.add("lf-flip");
}}
}}
function closeAll(except){{
var open=root.querySelectorAll(".lf-term.lf-open");
for(var i=0;i<open.length;i++){{
if(open[i]===except)continue;
open[i].classList.remove("lf-open");
var b=open[i].querySelector(".lf-help");
if(b)b.setAttribute("aria-expanded","false");
}}
}}
root.addEventListener("click",function(e){{
if(!e.target.closest)return;
if(e.target.closest(".lf-tip"))return;
var btn=e.target.closest(".lf-help");
if(!btn){{closeAll(null);return;}}
e.preventDefault();
var term=btn.parentNode;
var open=term.classList.contains("lf-open");
closeAll(term);
term.classList.toggle("lf-open",!open);
btn.setAttribute("aria-expanded",open?"false":"true");
}});
document.addEventListener("click",function(e){{
if(!root.contains(e.target))closeAll(null);
}});
document.addEventListener("keydown",function(e){{
if(e.key==="Escape")closeAll(null);
}});
window.addEventListener("resize",flip);
flip();

// --- 차트 ---
var DATA={payload};
var S1="{s1}",S2="{s2}",S3="{s3}";
function boot(){{
if(!window.echarts)return;
var ink="#3D4148",muted="#6B7280",grid="#e5e7eb",axis="#e5e7eb";
function base(){{return{{
grid:{{left:50,right:14,top:14,bottom:26}},
tooltip:{{trigger:"axis",axisPointer:{{type:"line",lineStyle:{{color:muted}}}},
valueFormatter:function(v){{return v==null?"-":v.toFixed(3)+"조";}}}},
xAxis:{{type:"category",data:DATA.dates,boundaryGap:false,
axisLine:{{lineStyle:{{color:axis}}}},axisTick:{{show:false}},
axisLabel:{{color:muted,fontSize:11}}}},
yAxis:{{type:"value",scale:true,splitLine:{{lineStyle:{{color:grid}}}},
axisLabel:{{color:muted,fontSize:11}}}},
textStyle:{{fontFamily:"'Outfit','Noto Sans KR',sans-serif",color:ink}}
}};}}
var charts=[];
function mk(id,opt){{
var el=document.getElementById(id);
if(!el)return;
var c=echarts.init(el);
c.setOption(opt);
charts.push(c);
}}
var o1=base();
o1.series=[{{name:"순유동성",type:"line",data:DATA.net_liquidity,showSymbol:false,
symbolSize:8,lineStyle:{{width:2,color:S1}},itemStyle:{{color:S1}},
areaStyle:{{color:S1,opacity:0.09}}}}];
mk("lfNetLiq",o1);
var o2=base();
o2.series=[
{{name:"국채",type:"line",stack:"bs",data:DATA.treasuries,showSymbol:false,
lineStyle:{{width:0}},itemStyle:{{color:S1}},areaStyle:{{color:S1,opacity:0.88}}}},
{{name:"MBS",type:"line",stack:"bs",data:DATA.mbs,showSymbol:false,
lineStyle:{{width:0}},itemStyle:{{color:S2}},areaStyle:{{color:S2,opacity:0.88}}}},
{{name:"기타",type:"line",stack:"bs",data:DATA.other,showSymbol:false,
lineStyle:{{width:0}},itemStyle:{{color:S3}},areaStyle:{{color:S3,opacity:0.88}}}}];
mk("lfBalance",o2);
window.addEventListener("resize",function(){{
charts.forEach(function(c){{c.resize();}});
}});
}}
if(window.echarts){{boot();return;}}
var s=document.createElement("script");
s.src="{ECHARTS_SRC}";
s.onload=boot;
document.head.appendChild(s);
}})();
</script>"""
