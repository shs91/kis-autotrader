# flow_filter 구조화 소스 — 투자자매매동향·공매도 일별추이 API (shadow)

## 메타데이터
- 작성: Claude Code (사용자 요청)
- 일자: 2026-06-14
- 상태: ready
- 우선순위: medium
- 카테고리: new_strategy
- 관련파일: `src/api/quote.py`, `src/strategy/flow_filter.py`, `tests/test_api/test_quote.py`, `tests/test_strategy/test_flow_filter.py`

## 현상 분석

- `2026-06-12_flow-filter-shadow.md`로 도입된 `flow_filter`는 **순수 스코어러**(미배선 shadow)이며, 수급 피처를 `news_chunks.chunk_text`의 **자유 텍스트에서 정규식으로 파싱**한다(`parse_flow_text`). 이 텍스트는 별도 `NewsCollectorWorker` 수집기가 긁어와 적재한 것이다.
- 텍스트 파싱 경로의 한계:
  1. **취약성** — 라벨/레이아웃(`기관합계 순매수:`, `당일 공매도 거래량:`)이 바뀌면 조용히 `None`이 되어 점수가 0으로 떨어진다(생존편향). 단위도 텍스트 포맷 의존(원/주 혼재).
  2. **커버리지 종속** — 수집기가 적재한 종목만 점수화 가능. 매매 후보(Top-K)를 on-demand로 점수화할 수 없다.
  3. **맥락 부재** — 공매도는 `잔고/거래량 수량`만 있고 **일중 거래량 대비 비중**이 없어 현재 `flow_score`에서 미반영 상태다.
- KIS OpenAPI는 동일 피처를 **구조화 JSON**으로 제공한다(엑셀 `docs/KIS_openAPI_260614.xlsx` 확인):
  - **종목별 투자자매매동향(일별)** `FHPTJ04160001` → `orgn_ntby_qty`(기관계)·`frgn_ntby_qty`(외국인)·`prsn_ntby_qty`(개인)·`fund_ntby_qty`(기금) 순매수 수량.
  - **국내주식 공매도 일별추이** `FHPST04830000` → `ssts_cntg_qty`(공매도 체결 수량)·**`ssts_vol_rlim`(공매도 거래량 비중 %)** — 텍스트 경로에 없던 일중 맥락.
- **두 API 모두 모의투자 미지원(실전 전용)**이다. 현재 런타임은 `virtual`(KRX)이므로, 본 변경은 **shadow(미배선)** 로만 들어가고 메서드는 모의 환경에서 방어적으로 `None`을 반환한다. 실효 가치는 **실전 전환 시점에 잠금 해제**된다(메모리 `project_kis_mock_api_limits`).

## 제안 내용

- `flow_filter`의 입력 소스를 **텍스트 파싱 → 구조화 API**로 전환하는 첫 단계로, `src/api/quote.py`에 두 수급 API의 **읽기 전용 조회 메서드 + DTO**를 추가한다. 모의 미지원/빈 응답/HTTP 에러 시 `None`을 반환(무동작 보장).
- `src/strategy/flow_filter.py`에는 구조화 필드(원시 정수)로부터 기존 `FlowFeatures`를 만드는 **순수 매퍼** `features_from_structured()`를 추가한다(전략 모듈 경계 준수 — api import 없음, 데이터를 인자로만 수신). 기존 `parse_flow_text`는 하위호환을 위해 **유지**한다.
- 점수 로직(`flow_score`)은 **변경하지 않는다**. 비율 기반이라 단위(원→주)에 불변이며, 텍스트 경로와 동일한 `FlowFeatures`를 생산해 회귀 위험을 0으로 만든다.

### 범위 밖 (본 제안 비포함 — 의도적)
- **엔진/스크리너 배선**(매매 판단에 `flow_score` 반영) — 매매경로 변경이므로 수동 계획 `docs/plans/2026-06-12_news-flow-data-utilization.md` Phase 3.
- **텍스트 수집기 폐기**(`parse_flow_text`/`news_chunks` 경로 제거) — 단계적 컷오버, 파일 삭제 금지 규칙 준수.
- **공매도 잔고(short_balance)** — 별도 API(대차거래/공매도 잔고)이며 본 일별추이 API는 거래량/비중만 제공.
- `ssts_vol_rlim` **스코어링 반영** — DTO로 노출만 하고 `flow_score`는 이번에 미변경(향후 확장 여지).

## 변경 스펙

### 1. `src/api/quote.py` — 수급 조회 메서드 2종 + DTO 추가

**(a) 엔드포인트/TR_ID 상수 추가** (기존 상수 블록, `TR_ID_VOLUME_RANK` 아래에):

```python
# 수급(투자자매매동향·공매도) — 모두 모의투자 미지원(실전 전용)
INVESTOR_TREND_PATH: str = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
SHORT_SALE_PATH: str = "/uapi/domestic-stock/v1/quotations/daily-short-sale"
TR_ID_INVESTOR_TREND: str = "FHPTJ04160001"
TR_ID_SHORT_SALE: str = "FHPST04830000"
```

**(b) DTO 추가** (`VolumeRankItem` 아래에):

```python
@dataclass
class InvestorTrendDaily:
    """종목별 투자자매매동향(일별) 최신 1건 — 순매수 수량(단위: 주)."""

    stock_code: str
    date: str
    institution_net_qty: int  # orgn_ntby_qty 기관계
    foreign_net_qty: int  # frgn_ntby_qty 외국인
    individual_net_qty: int  # prsn_ntby_qty 개인
    pension_net_qty: int  # fund_ntby_qty 기금(연기금 proxy)


@dataclass
class ShortSaleDaily:
    """국내주식 공매도 일별추이 최신 1건."""

    stock_code: str
    date: str
    short_volume_qty: int  # ssts_cntg_qty 공매도 체결 수량(주)
    short_volume_ratio: float  # ssts_vol_rlim 공매도 거래량 비중(%)
```

**(c) 모듈 상단 import에 `KISAutoTraderError` 추가** (방어적 except용):

```python
from src.utils.exceptions import KISAutoTraderError
```

**(d) `QuoteAPI`에 메서드 2종 추가** (`get_volume_rank` 아래에):

```python
    async def get_investor_trend_daily(
        self,
        stock_code: str,
        market: str = "J",
        query_date: str | None = None,
    ) -> InvestorTrendDaily | None:
        """종목별 투자자매매동향(일별) 최신 1건을 조회한다(FHPTJ04160001).

        **모의투자 미지원(실전 전용)**. 모의 환경/에러/빈 응답에서는 None을
        반환하여 호출부 무동작을 보장한다. 당일 데이터는 장 종료 후 확정된다.

        Args:
            stock_code: 종목코드 (6자리)
            market: 시장 구분 ("J": KRX, "NX": NXT, "UN": 통합)
            query_date: 조회 일자(YYYYMMDD). 미지정 시 오늘.

        Returns:
            최신 1건 또는 None
        """
        logger.debug("[투자자매매동향 조회] 종목=%s", stock_code)

        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": query_date or date.today().strftime("%Y%m%d"),
            "FID_ORG_ADJ_PRC": "",
            "FID_ETC_CLS_CODE": "1",
        }
        try:
            response = await self._client.get(
                INVESTOR_TREND_PATH,
                headers={"custtype": "P"},
                params=params,
                tr_id=TR_ID_INVESTOR_TREND,
            )
        except KISAutoTraderError:
            logger.debug("[투자자매매동향] 미지원/에러 — 종목=%s", stock_code)
            return None

        if str(response.get("rt_cd", "0")) != "0":
            return None
        output_list = response.get("output2") or []
        if not output_list:
            return None
        item = output_list[0]  # 응답 선두 = 최신 일자
        return InvestorTrendDaily(
            stock_code=stock_code,
            date=_get(item, "STCK_BSOP_DATE"),
            institution_net_qty=int(_get(item, "ORGN_NTBY_QTY", "0") or "0"),
            foreign_net_qty=int(_get(item, "FRGN_NTBY_QTY", "0") or "0"),
            individual_net_qty=int(_get(item, "PRSN_NTBY_QTY", "0") or "0"),
            pension_net_qty=int(_get(item, "FUND_NTBY_QTY", "0") or "0"),
        )

    async def get_short_sale_daily(
        self,
        stock_code: str,
        market: str = "J",
    ) -> ShortSaleDaily | None:
        """국내주식 공매도 일별추이 최신 1건을 조회한다(FHPST04830000).

        **모의투자 미지원(실전 전용)**. 모의 환경/에러/빈 응답에서는 None을
        반환한다.

        Args:
            stock_code: 종목코드 (6자리)
            market: 시장 구분 ("J": 주식)

        Returns:
            최신 1건 또는 None
        """
        logger.debug("[공매도 일별추이 조회] 종목=%s", stock_code)

        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": "",
            "FID_INPUT_DATE_2": date.today().strftime("%Y%m%d"),
        }
        try:
            response = await self._client.get(
                SHORT_SALE_PATH,
                headers={"custtype": "P"},
                params=params,
                tr_id=TR_ID_SHORT_SALE,
            )
        except KISAutoTraderError:
            logger.debug("[공매도 일별추이] 미지원/에러 — 종목=%s", stock_code)
            return None

        if str(response.get("rt_cd", "0")) != "0":
            return None
        output_list = response.get("output2") or []
        if not output_list:
            return None
        item = output_list[0]
        return ShortSaleDaily(
            stock_code=stock_code,
            date=_get(item, "STCK_BSOP_DATE"),
            short_volume_qty=int(_get(item, "SSTS_CNTG_QTY", "0") or "0"),
            short_volume_ratio=float(_get(item, "SSTS_VOL_RLIM", "0") or "0"),
        )
```

> 비고: `_get`는 대/소문자 키를 모두 시도하므로 KIS의 소문자 응답 필드와 호환된다. `headers={"custtype": "P"}`는 두 API가 `custtype` 필수(Y)이나 `_build_headers`가 기본 설정하지 않으므로 명시 전달한다.

### 2. `src/strategy/flow_filter.py` — 구조화 매퍼 추가 (순수, api import 없음)

기존 `parse_flow_text` 아래(또는 `flow_score` 위)에 추가. 기존 함수/시그니처는 무변경:

```python
def features_from_structured(
    *,
    institution_net: int | None = None,
    foreign_net: int | None = None,
    individual_net: int | None = None,
    pension_net: int | None = None,
    short_volume_qty: int | None = None,
) -> FlowFeatures:
    """구조화 수급 API 필드로부터 FlowFeatures를 만든다(텍스트 파싱 대체 경로).

    값 단위는 '주'(수량)이며 flow_score는 비율이라 단위에 불변하다. 텍스트
    경로 parse_flow_text와 동일한 FlowFeatures를 생산해 flow_score를 그대로
    재사용한다. 전략 모듈 경계 준수 — DB/API 객체가 아닌 원시 정수만 받는다.
    """
    return FlowFeatures(
        institution_net=institution_net,
        foreign_net=foreign_net,
        individual_net=individual_net,
        pension_net=pension_net,
        short_volume_qty=short_volume_qty,
    )
```

> Phase 3 배선 시 호출부(엔진, read-only)는 다음과 같이 사용한다(본 제안 범위 밖, 참고용):
> ```python
> trend = await quote_api.get_investor_trend_daily(code)
> if trend is not None:
>     feat = features_from_structured(
>         institution_net=trend.institution_net_qty,
>         foreign_net=trend.foreign_net_qty,
>         individual_net=trend.individual_net_qty,
>         pension_net=trend.pension_net_qty,
>     )
>     score = flow_score(feat)  # [-1.0, 1.0]
> ```

### 3. 추가 테스트

**`tests/test_api/test_quote.py`** — `TestQuoteAPI`에 추가(기존 AsyncMock 패턴 사용):

```python
    async def test_get_investor_trend_daily_success(self) -> None:
        """투자자매매동향 최신 1건을 파싱한다(output2 선두)."""
        response = {
            "rt_cd": "0",
            "output2": [
                {
                    "STCK_BSOP_DATE": "20260612",
                    "ORGN_NTBY_QTY": "107145",
                    "FRGN_NTBY_QTY": "-1091127",
                    "PRSN_NTBY_QTY": "861030",
                    "FUND_NTBY_QTY": "66255",
                }
            ],
        }
        api = self._make_quote_api(response)
        result = await api.get_investor_trend_daily("005880")
        assert result is not None
        assert result.institution_net_qty == 107145
        assert result.foreign_net_qty == -1091127  # 음수(순매도) 처리
        assert result.individual_net_qty == 861030
        assert result.date == "20260612"

    async def test_get_investor_trend_daily_none_on_mock_unsupported(self) -> None:
        """모의 미지원(HTTP 에러)이면 None을 반환한다."""
        from src.utils.exceptions import KISAutoTraderError

        mock_client = AsyncMock()
        mock_client.get.side_effect = KISAutoTraderError("API 에러 (status=500)")
        api = QuoteAPI(client=mock_client)
        assert await api.get_investor_trend_daily("005930") is None

    async def test_get_investor_trend_daily_none_on_empty(self) -> None:
        """빈 output2 또는 rt_cd!=0이면 None을 반환한다."""
        api = self._make_quote_api({"rt_cd": "0", "output2": []})
        assert await api.get_investor_trend_daily("005930") is None
        api2 = self._make_quote_api({"rt_cd": "7", "msg1": "모의투자 미지원"})
        assert await api2.get_investor_trend_daily("005930") is None

    async def test_get_short_sale_daily_success(self) -> None:
        """공매도 일별추이 최신 1건을 파싱한다(비중 포함)."""
        response = {
            "rt_cd": "0",
            "output2": [
                {
                    "STCK_BSOP_DATE": "20260612",
                    "SSTS_CNTG_QTY": "584958",
                    "SSTS_VOL_RLIM": "12.34",
                }
            ],
        }
        api = self._make_quote_api(response)
        result = await api.get_short_sale_daily("005880")
        assert result is not None
        assert result.short_volume_qty == 584958
        assert result.short_volume_ratio == 12.34

    async def test_get_short_sale_daily_none_on_error(self) -> None:
        """HTTP 에러 시 None을 반환한다."""
        from src.utils.exceptions import KISAutoTraderError

        mock_client = AsyncMock()
        mock_client.get.side_effect = KISAutoTraderError("boom")
        api = QuoteAPI(client=mock_client)
        assert await api.get_short_sale_daily("005930") is None
```

**`tests/test_strategy/test_flow_filter.py`** — 매퍼 동등성 검증 추가:

```python
def test_features_from_structured_matches_text_path() -> None:
    """구조화 매퍼가 텍스트 경로와 동일한 flow_score를 만든다."""
    from src.strategy.flow_filter import features_from_structured

    feat = features_from_structured(
        institution_net=100, foreign_net=50, individual_net=-150
    )
    assert flow_score(feat) == 150 / 300  # 텍스트 경로 test와 동일 값


def test_features_from_structured_partial_is_safe() -> None:
    """수급 항목이 없으면 flow_score 0.0(안전)."""
    from src.strategy.flow_filter import features_from_structured

    assert flow_score(features_from_structured(short_volume_qty=1000)) == 0.0
```

## 기대 효과

- **신뢰성**: 라벨/레이아웃 의존 정규식 → 구조화 JSON 필드 직접 매핑. 텍스트 변형에 의한 조용한 0점화(생존편향) 제거.
- **커버리지**: 수집기 적재 종목에 한정되던 점수화를, 임의 종목 on-demand 조회로 확장(Phase 3에서 Top-K 후보 전수 수급 점수화 가능).
- **신규 피처 확보**: `ssts_vol_rlim`(공매도 비중 %)로 일중 맥락 확보 → 향후 공매도 스코어링 기반 마련.
- **리스크 0**: shadow(미배선) + 모의 환경 `None` 반환(무동작)이라 실거래 동작 무변경. 측정·검증 인프라의 다음 조각.

## 롤백

- 변경 4파일 모두 추가(append)·신규 테스트뿐. `git restore`로 즉시 원복.
- `config_overrides.json`·DB 스키마·`.env`·외부 패키지·기존 함수 시그니처에 영향 없음. 매매 경로 무변경.
