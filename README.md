# liquidity-feed

미국 유동성 지표를 FRED 에서 주 1회 수집해 MQWAY 게시판에 올릴 HTML 게시물과
JSON 스냅샷을 만드는 프로젝트.

웹 화면은 이 프로젝트의 범위가 아니다. 데이터 생산까지만 책임진다.

## 무엇을 하는가

1. FRED 에서 유동성 관련 시계열 26개를 수집한다
2. FRED 메타데이터로 단위와 주기를 확인하고 정규화한다
3. 파생 지표(순유동성, 지준/GDP, 예대율 등)를 계산한다
4. 레이어별 스냅샷 JSON 을 만든다
5. MQWAY 게시판에 올릴 HTML 본문을 생성해 API 로 전송한다

## 현재 상태

| 부분 | 상태 |
|---|---|
| `config/series.yaml` | 26개 시리즈 확정. 전량 수집 확인 |
| `config/thresholds.yaml` | 용어와 해설 문구 작성. 임계치는 미정 |
| `config/schedule.yaml` | 일정 확정 |
| `fred_service.py` | 동작. FRED 수집과 파생 지표 계산 |
| `report_generator.py` | 동작. 게시물 HTML, 확인용 문서, 썸네일 생성 |
| `utils/api_util.py` | 동작. MQWAY 전송 |
| `main.py` | 동작. 수집부터 게시까지 한 번에, 환경 자가진단 |
| raw 저장 / 증분 수집 | 미구현. FRED 가 호출마다 전체 히스토리를 주므로 급하지 않다 |

## 데이터 출처

FRED (Federal Reserve Bank of St. Louis)

- 공식 API: `https://api.stlouisfed.org/fred/series/observations`
- 무료 API 키 필요: https://fred.stlouisfed.org/docs/api/api_key.html
- 키는 환경변수 `FRED_API_KEY` 로 주입한다. 코드나 저장소에 하드코딩 금지.

메타데이터는 두 단계로 받는다. `/fred/series` 응답에는 출처 기관이 없다.

```
/fred/series?series_id=X          units, frequency, seasonal_adjustment, title
/fred/series/release?series_id=X  릴리스 (예: H.4.1 Factors Affecting Reserve Balances)
/fred/release/sources?release_id  출처 기관 (예: Board of Governors of the Federal Reserve System)
```

릴리스는 여러 시리즈가 공유하므로 release_id 로 캐시하면 26개에 릴리스 호출 10여 회로 끝난다.

개발 중 확인용 백업 경로:

```
https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
```

- API 키 없이 값을 받는다. 헤더는 `observation_date,<SERIES_ID>`
- 여러 id 를 콤마로 주면 ZIP 으로 떨어지므로 반드시 시리즈별 단건 호출
- **전체 히스토리를 주지 않는다.** 공식 API 가 값 없는 앞쪽 날짜까지 포함해
  돌려주는 데 반해 CSV 는 실제 값이 있는 구간만 준다. WRESBAL 기준 API 2229행,
  CSV 1240행이다. 차이 989행은 전부 값이 비어 있는 행이라 데이터 손실은 없지만,
  행 수를 비교하는 검사에서는 이 차이를 감안해야 한다
- 문서화된 API 가 아니므로 운영에서는 쓰지 않는다

두 경로의 값은 겹치는 날짜에서 완전히 일치한다. 26개 시리즈 전량을
대조해 확인했다.

## 수집 대상 시리즈

괄호 안의 단위와 주기는 참고용이다. 실제 값은 FRED `/fred/series` 응답의
`units`, `units_short`, `frequency`, `seasonal_adjustment` 를 함께 수집해
저장하고, 환산 로직이 그 값을 참조한다. 코드에 하드코딩하지 않는다.

Layer 1 - 지급준비금 / 은행시스템 유동성
```
WRESBAL          지급준비금 주간평균 (Millions, Weekly Ending Wednesday)
WRBWFRBL         지급준비금 수요일 시점 (Millions, Weekly As of Wednesday)
GDP              명목 GDP (Billions, Quarterly, SAAR)
```

Layer 2 - TGA / RRP / 단기 유동성 배관
```
WTREGEN          재무부 일반계정 TGA 주간평균 (Millions, Weekly Ending Wednesday)
WDTGAL           재무부 일반계정 TGA 수요일 시점 (Millions, Weekly As of Wednesday)
RRPONTSYD        익일물 역레포 (Billions, Daily)
```

Layer 3 - Fed 대차대조표 / QT
```
WALCL            Fed 총자산 (Millions, Weekly As of Wednesday)
WSHOSHO          Fed 보유 증권 전체 (Millions, Weekly As of Wednesday)
WSHOTSL          Fed 보유 국채 (Millions, Weekly As of Wednesday)
WSHOMCB          Fed 보유 MBS (Millions, Weekly As of Wednesday)
```

Layer 4 - M2 / 은행 신용창조
```
M2SL             M2 통화량 (Billions, Monthly)
M2V              M2 유통속도 (Ratio, Quarterly)
TOTLL            은행 총대출 (Billions, Weekly Ending Wednesday)
DPSACBW027SBOG   은행 예금 (Billions, Weekly Ending Wednesday)
```

Layer 5 - 재정 / 국채
```
WTREGEN / WDTGAL TGA (Layer 2 와 공유)
FYGFDPUB         공공보유 연방부채 (Billions, Annual Fiscal Year)
DTB4WK           4주물 국채 유통수익률 (Percent, Daily)
```

Layer 6 - MMF / 시장 내부 유동성
```
MMMFFAQ027S      MMF 총자산 (Millions, Quarterly End of Period)
```

Layer 7 - 신용경색
```
CREACBW027SBOG   상업용부동산 대출 (Billions, Weekly Ending Wednesday)
BUSLOANS         상공업 대출 (Billions, Monthly)
DRTSCILM         대기업 대출기준 강화 비율 (Percent, Quarterly)
DRTSCIS          중소기업 대출기준 강화 비율 (Percent, Quarterly)
STLFSI4          세인트루이스 연준 금융스트레스지수 (Index, Weekly Ending Friday)
NFCI             시카고 연준 전미금융여건지수 (Index, Weekly Ending Friday)
```

금리 참조
```
SOFR             담보부 익일물 조달금리 (Percent, Daily)
EFFR             실효 연방기금금리 (Percent, Daily)
FEDFUNDS         연방기금금리 월평균 (Percent, Monthly)
```

### 제외한 시리즈

```
RESBALNS    2020-08-01 단종. FRED title 에 (DISCONTINUED) 가 붙어 있고
            last_updated 가 2020-09-10 이다. WRBWFRBL 로 대체했다
DTBSPCKFM   4주물 국채 수익률이 아니다. 실제 title 은 Financial Commercial
            Paper Outstanding (금융 CP 잔액, 금액 지표). DTB4WK 로 대체했다
```

### 단위와 주기에서 사고 나기 쉬운 곳

```
WALCL / WTREGEN / WRESBAL / WSHO* 는 Millions, RRPONTSYD 는 Billions.
같은 달러 지표라도 스케일이 1000 배 차이난다.

GDP 도 Billions 다. WRESBAL(Millions) 을 그냥 나누면 비율이 1000 배로 나온다.
reserves_to_gdp 정답은 9.28% 인데 단위를 무시하면 92.77 이 된다.

WSHOSHO 는 보유 국채가 아니라 보유 증권 전체다(국채 + MBS + 에이전시).
국채만 필요하면 WSHOTSL 을 쓴다. WSHOTSL + WSHOMCB <= WSHOSHO <= WALCL 이
성립하는지 검사한다.

주기 문자열이 세 가지다. 같은 "주간" 이라도 기준일과 측정 방식이 다르다.
  Weekly, As of Wednesday   수요일 그 시점 잔액
  Weekly, Ending Wednesday  수요일로 끝나는 주의 평균
  Weekly, Ending Friday     금요일로 끝나는 주
2026-09-16 기준 TGA 는 주간평균 877,028 M 인데 수요일 시점은 991,708 M 로
114,680 M 차이가 난다. 섞어 쓰면 순유동성이 0.12 조 달러 흔들린다.
```

### 결측 처리

FRED 결측치는 `.` 로 온다. NULL 로 변환하고 **0 으로 채우지 않는다.**
결측은 세 종류가 섞여 있다.

```
선행 결측   값이 시작되기 전 빈 행. WRESBAL 989건(1984-2002), WTREGEN 884건
휴일 결측   일간 시리즈의 미국 공휴일. SOFR 95건, EFFR 258건, DTB4WK 273건
미실시      RRPONTSYD 2832건. 역레포 운영이 없던 날이라 0 과 뜻이 다르다
```

최신값은 마지막 행이 아니라 **마지막 값 있는 행**이어야 한다.

## 게시 금지 시리즈

```
BAMLH0A0HYM2     하이일드 OAS 스프레드
BAMLH0A0HYM2EY   하이일드 유효수익률
```

ICE Data Indices 저작권 자료다. FRED 시리즈 노트 원문:

> Reproduction of this data in any form is prohibited except with the
> prior written permission of ICE Data Indices.

수집 대상에서 제외한다. 신용경색은 STLFSI4 / NFCI 로 대체한다.
내부 참고용으로라도 외부 노출 JSON 이나 게시물에 절대 포함하지 않는다.

`tests/test_config.py` 가 이 목록이 수집 대상에 섞이지 않는지 검사하고,
`main.py` 의 제약 검사가 생성된 본문에 나타나지 않는지 다시 검사한다.

## 법적 의무

1. FRED API 이용약관에 따라 아래 문구를 소비처 화면에 노출해야 한다.

   > This product uses the FRED(R) API but is not endorsed or certified
   > by the Federal Reserve Bank of St. Louis.

   생성하는 JSON 의 `meta.disclaimer` 와 HTML 게시물 하단에 항상 넣는다.

2. 연준 로고와 상표는 사용하지 않는다.

3. 시리즈별 출처 기관과 인용 문구를 FRED 메타에서 받아 실어 보낸다.
   하드코딩 금지. 게시물 본문에는 `출처 FRED` 한 줄만 두고, 기관별 상세는
   `latest.json` 의 `meta.sources` 가 담당한다.

4. FRED 의 핵심 사용자 경험을 복제하거나 대체하는 형태
   (예: 범용 시리즈 검색기) 는 약관 위반 소지가 있으므로 만들지 않는다.

5. 참고한 대시보드의 한국어 판정 문구와 임계치 설명은 그쪽 창작물이다.
   복사하지 않는다. 임계치와 해설은 직접 정의해 `config/thresholds.yaml` 로
   관리하고 코드와 분리한다. `report_generator.py` 에는 설명 문구가 한 줄도 없다.

## 파생 지표

```
net_liquidity     = WALCL - WDTGAL - RRPONTSYD(해당 수요일)
reserves_to_gdp   = WRESBAL / GDP
loan_to_deposit   = TOTLL / DPSACBW027SBOG
delta_week        = 각 지표의 주간 변화
delta_month       = 각 지표의 월간 변화
```

순유동성은 **수요일 시점값으로 통일한다.** WALCL 이 As of Wednesday 이므로
TGA 도 주간평균인 WTREGEN 이 아니라 수요일 시점인 WDTGAL 을 쓰고, 역레포는
일간 시리즈에서 해당 수요일 값을 집는다. WTREGEN 과 WRESBAL 은 계산에
쓰지 않고 참조용으로만 싣는다.

계산 전에 전부 조 달러로 정규화한다. GDP 는 SAAR(연율 계절조정)이므로
`reserves_to_gdp` 는 "지준 / 연율 GDP" 로 정의된다.

변화율은 잔액이 0 에 가까우면 뜻을 잃는다. 역레포가 0.43B 에서 5.375B 로
움직이면 +1144% 가 되므로, 절대값이 작을 때는 변화율 대신 금액 차이를 쓴다.

파생 지표는 원천값과 분리해 언제든 재계산할 수 있게 한다.

## 저장

**DB 를 쓰지 않는다.** FRED 가 호출마다 전체 히스토리를 주고 최종 결과는
MQWAY 에 적재되므로 중간에 둘 저장소가 필요 없다. 26개 시리즈 전량 수집이
약 30초, 원본 JSON 합계 4.5 MB 다.

단계 사이에 데이터를 넘길 때는 원본 응답 파일을 쓴다.

```
output/raw/<YYYY-MM-DD>/<SERIES_ID>.json   FRED 응답 원본
output/raw/<YYYY-MM-DD>/meta.json          시리즈 메타와 출처
output/raw/<YYYY-MM-DD>/run.json           실행 기록. 시리즈별 성공 여부와 오류
```

최근 8회분만 남기고 지운다(`config/schedule.yaml` 의 `retention.raw_runs`).
직전 회차가 있으면 개정된 값을 찾아낼 수 있다. FRED 는 과거 값을 조용히
고치므로 이 비교가 유일한 감지 수단이다.

## 산출물

```
output/export/latest.json
  {
    "meta": { "generated_at": ..., "as_of_label": ..., "disclaimer": "...",
              "sources": [{ "name": ..., "release": ... }] },
    "layers": [
      { "layer": 1, "series_id": "...", "name_ko": "...", "display": "...",
        "delta_week": ..., "delta_month": ..., "as_of": "..." }
    ],
    "derived": { "net_liquidity": ..., "reserves_to_gdp": ... }
  }

output/export/series/<SERIES_ID>.json   시리즈별 시계열 (차트용)
output/export/post.html                 MQWAY 게시용 HTML 본문 (조각)
output/export/preview.html              post.html 을 브라우저에서 확인하는 용도
```

`output/export/` 는 저장소에 커밋하지 않는다. 생성 스크립트만 커밋한다.

## CLI

```
python main.py               FRED 수집 -> post.html -> 제약 검사 -> preview.html
python main.py --send        위와 같고 MQWAY 로 실제 전송까지 한다
python main.py --check       환경 자가진단
python main.py --thumbnail   img/thumbnail.png 생성 (한 번만)
```

- **기본값이 전송 안 함**이다. `--send` 를 붙여야 실제로 올라간다.
  실서버에 잘못 올라간 글은 지우기 전까지 되돌릴 수 없어서 이렇게 뒤집었다.
- `--check` 는 스케줄러에 걸기 전에 한 번 돌린다.
- 제약 검사를 하나라도 통과하지 못하면 게시하지 않고 종료 코드 1 을 낸다.
- 전송 실패는 생성 실패가 아니다. post.html 은 이미 저장돼 있어 나중에
  다시 보낼 수 있으므로 종료 코드 0 을 유지한다.

## 스케줄

`config/schedule.yaml` 에 정의한다.

```
매주 토요일 08:00 KST, 단일 실행
  fetch -> derive -> export -> publish
```

토요일인 이유는 발표 일정이다. FRED 타임스탬프는 세인트루이스 연준 기준이라
미 중부시간이다.

```
H.4.1 (총자산, TGA, 지준, 국채, MBS)  목 15:31 CT -> 금 05:31 KST (겨울 06:31)
H.8   (은행 대출, 예금, 상업용부동산)  금 15:18 CT -> 토 05:18 KST (겨울 06:18)
```

금요일에 돌리면 H.8 이 한 주 묵은 값으로 들어간다. 토요일이면 둘 다 그 주
최신이다. 08:00 은 서머타임 양쪽을 덮으려고 잡은 시각이다.

수집을 더 자주 할 이유는 없다. FRED 가 호출마다 전체 시계열을 주므로
토요일 한 번 호출에 그 주 평일 값이 전부 따라온다. 26개 중 매일 바뀌는 것은
RRPONTSYD / DTB4WK / SOFR / EFFR 네 개뿐이고, 이것도 주 1회 호출에 다 담긴다.
`output/export/series/*.json` 을 매일 갱신해야 하는 화면이 생기면 그때 매일로
바꾼다.

재시도는 두 층이다.

```
실행 단위   30분 간격 3회. 그래도 실패하면 게시를 건너뛴다
호출 단위   시리즈 간 0.5초 간격. 429 / 5xx 는 지수 백오프 4회
```

실패하면 `logs/` 에 남기고 텔레그램으로 알린다. 새벽에 조용히 실패하면
알 방법이 없기 때문이다. **전송 실패는 생성 실패가 아니다.** `post.html` 은
이미 저장돼 있으므로 종료 코드 0 을 유지하고 나중에 다시 보내면 된다.
알림 전송이 실패해도 게시가 됐으면 성공으로 본다.

FRED 는 구체적 rate limit 수치를 공개하지 않는다. 주 1회 26건이면 부담이 없다.

**H.8 은 구조적으로 한 주 뒤처진다.** 금요일에 나오는 H.8 이 담는 것은 그
전주 수요일 자료다. 토요일에 받아도 대출과 예금은 총자산보다 한 주 과거다.
발행일을 옮겨서 해결되지 않으므로 게시물 표에 지표마다 기준일을 적는다.

## MQWAY 연동

최종 결과물은 mqway.com 게시판에 HTML 게시물로 올라간다.
MQWAY 본체는 Laravel 6 이며 외부 프로그램이 게시글을 POST 하는 통로가 이미 있다.

전송 방식
```
POST {BASE_URL}/api/board-research
  title     제목 (필수, 255자 이내)
  content   HTML 본문 (필수)
  category  카테고리 (필수, 50자 이내)
  writer    작성자 ID (필수, 50자 이내) -> admin 고정
```

`board-*` 엔드포인트에는 인증 미들웨어가 없다. 별도 키 없이 URL 로 바로
POST 한다. 게시판은 `board-research`, 작성자는 `admin`, 카테고리는 `유동성`
으로 고정이므로 환경변수로 받지 않는다. 게시판은 `utils/api_util.py`, 작성자와
카테고리는 `main.py` 에 둔다.

응답에서 주의할 점 두 가지다. 형제 프로젝트 krx-daily-brief 의
`utils/api_util.py` 에서 확인한 규약이다.

```
HTTP 200 이어도 본문 success 가 false 면 실패다. 상태 코드만 보면 안 된다
생성된 게시글 번호는 data.id 로 온다 -> {BASE_URL}/board-research/{id}
```

썸네일이 있으면 multipart 로, 없으면 JSON 으로 보낸다. 썸네일은 800px 로
줄이고 1MB 를 넘으면 JPEG 품질을 낮춘다. 썸네일 처리가 실패해도 게시는
그대로 진행한다.

본문은 MQWAY 상세 화면에서 이스케이프 없이 그대로 렌더된다
(`board_research/show.blade.php` 의 `{!! $post->mq_content !!}`).
따라서 div, table, script 태그가 모두 동작한다.

### 지켜야 할 제약 4가지

1. **본문 길이**
   `mq_content` 컬럼이 MySQL `text` 타입이라 64KB 가 상한이다.
   현재 본문은 약 23KB 로 상한의 35% 다. 104주치 시계열 4개를 인라인으로
   넣고도 여유가 있어 외부 JSON fetch 없이 자체 완결로 만들었다.
   시리즈를 더 넣어 한계에 닿으면 외부 JSON 을 fetch 하는 방식으로 바꾸거나
   MQWAY 쪽에서 컬럼을 `mediumtext` 로 올려야 한다.

2. **차트 라이브러리**
   게시판 상세 화면에는 ECharts 가 로드돼 있지 않다(`/board` 확인).
   본문 HTML 안에 CDN script 태그를 직접 포함한다. MQWAY 메인이 쓰는
   `cdn.jsdelivr.net/npm/echarts@5.4.3` 에 버전을 맞춘다.

3. **목록 미리보기**
   게시판 목록은 `strip_tags()` 로 본문에서 텍스트만 뽑아 미리보기를 만든다.
   본문 최상단에 개조식 요약을 둬서 미리보기가 비지 않게 한다.

4. **CSS 격리**
   본문이 MQWAY 페이지에 그대로 삽입되므로 선택자를 전부 `.lf-root` 아래로
   한정한다. `body`, `html`, `*`, `:root` 같은 전역 선택자와 `!important` 를
   쓰지 않는다. `main.py` 의 제약 검사가 이를 확인한다.

### 게시판 선택

- `board-research`, `board-insights` 는 로그인해야 열람 가능
  (`/board-research` 가 `/login` 으로 302)
- `board-content`, `board` 는 비회원도 열람 가능

현재 대상은 `board-research` 다.

### 게시물 디자인

MQWAY 사이트 톤에 맞춘다. `mqway.com` 의 `tailwind.config` 에서 확인한 값이다.

```
배경 #F8F9FA   카드 #FFFFFF   테두리 #e5e7eb   잉크 #2D3047
액센트 #FF4D4D   서체 Noto Sans KR / Outfit (MQWAY 가 이미 로드한다)
```

**라이트 전용이다.** MQWAY 에는 다크모드가 없다(`prefers-color-scheme` 0건).
본문이 OS 설정을 따라 어두워지면 흰 페이지 위에 검은 블록이 떠버린다.

차트 색은 MQWAY 브랜드 색조를 유지한 채 밝기와 채도만 접근성 통과 구간으로
스냅한 값이다. 브랜드 원색은 너무 밝아 대비 검증을 통과하지 못한다.

```
코랄 #FF4D4D -> #EB383D    민트 #4ECDC4 -> #009D94    앰버 #FFB347 -> #BA7500
```

순서가 안전장치다. 코랄과 앰버를 붙이면 적록색약 분리도가 2.4 로 떨어지므로
반드시 민트를 사이에 둔다.

용어는 정식 명칭을 그대로 쓰고, 설명이 필요한 것에는 물음표 버튼을 붙여
툴팁으로 보여준다. 문구는 `config/thresholds.yaml` 에 있다.

## 환경변수

```
FRED_API_KEY             FRED API 키 (필수)
BASE_URL                 MQWAY 사이트 주소 (필수). 스킴과 호스트까지만 적는다
                         /api 는 코드가 붙인다. 기본값을 두지 않는다
TELEGRAM_BOT_TOKEN       텔레그램 알림 (선택, 권장)
TELEGRAM_CHAT_ID         성공 알림이 가는 방
TELEGRAM_CHAT_TEST_ID    실패 알림이 가는 방. 비우면 위 방으로 간다
```

`BASE_URL` 은 형제 프로젝트 krx-daily-brief 와 같은 이름, 같은 규칙이다.
`.env` 를 공유할 수 있다.

```
BASE_URL=http://localhost   ->   http://localhost/api/board-research
```

**`BASE_URL` 에 기본값을 두지 않는다.** 기본값이 있으면 `.env` 를 빠뜨린 채
`--send` 했을 때 운영 서버로 글이 올라간다.

게시판(`board-research`), 작성자(`admin`), 카테고리(`유동성`)는 고정값이라
환경변수로 받지 않는다. MQWAY 인증 키는 없다. DB 를 쓰지 않으므로
`DATABASE_URL` 도 없다.

`.env` 는 저장소에 커밋하지 않는다. `.env.example` 만 둔다.

## 기술 스택

python 3.12, httpx, pandas, pydantic (스키마 검증), pyyaml, python-dotenv,
pytest, ruff. 가상환경은 `.venv` 를 쓴다.

패키지로 설치하지 않는다. 의존성은 `requirements.txt` 하나로 관리하고
실행과 테스트 모두 프로젝트 루트에서 한다.

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

테스트와 린트도 루트에서 `python -m` 으로 부른다. 설치를 안 하므로
`pytest` 를 바로 부르면 `utils` 를 못 찾는다.

```
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
```

## 디렉터리 구조

```
liquidity-feed/
  README.md
  requirements.txt
  .env.example
  config/
    series.yaml          수집 대상 시리즈 정의
    thresholds.yaml      용어, 해설 문구, 레이어별 임계치
    schedule.yaml        수집과 게시 일정
  main.py                진입점. 수집 -> 생성 -> 검사 -> 게시, 환경 자가진단
  fred_service.py        FRED 수집(FredDataCollector)과 파생 지표 계산(LiquidityCalculator)
  report_generator.py    post.html / latest.json / preview.html / 썸네일 생성
  utils/
    api_util.py          MQWAY API 전송
    logger_util.py       로그 설정 (logs/ 에 날짜별)
    telegram_util.py     텔레그램 알림
  img/
    thumbnail.png        게시판 목록 카드 이미지
  output/
    raw/                 FRED 응답 원본 (최근 8회분)
    export/              산출물
  logs/                  실행 로그 (커밋하지 않는다)
  tests/
```

## 검증 기준

1. 게시 금지 2개를 뺀 26개 시리즈가 전부 수집된다
2. WRESBAL 2026-09-16 값이 3013794 (Millions) 로 들어온다
3. WTREGEN 2026-09-16 값이 877028 (Millions) 로 들어온다
4. 단위 환산 후 지급준비금이 3.013794 (조 달러) 로 나온다
5. `latest.json` 에 disclaimer 문구가 포함된다
6. BAMLH0A0HYM2 계열이 JSON, HTML 어디에도 나타나지 않는다
7. 같은 입력으로 두 번 실행하면 같은 결과가 나온다
8. 공식 API 와 CSV 두 경로의 값이 겹치는 날짜에서 모두 일치한다
9. `WSHOTSL + WSHOMCB <= WSHOSHO <= WALCL` 이 성립한다
10. 생성된 `post.html` 이 64KB 미만이고 최상단에 텍스트 요약이 있다
11. 게시물 CSS 선택자가 전부 `.lf-` 아래로 한정된다
12. 같은 지표가 게시물 안에서 두 값으로 나오지 않는다
    (역레포는 일간이라 표와 타일의 기준일을 맞춰야 한다)
