"""백테스트용 과거 데이터 로더."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.api.client import KISClient
from src.api.quote import QuoteAPI
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DataLoader:
    """과거 일봉 데이터를 로드한다.

    CSV 파일 또는 KIS API를 통해 일봉 데이터를 DataFrame으로 제공한다.
    반환되는 DataFrame은 date, open, high, low, close, volume 컬럼을 가지며
    날짜 오름차순으로 정렬된다.
    """

    REQUIRED_COLUMNS: tuple[str, ...] = (
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    def from_csv(self, file_path: str | Path) -> pd.DataFrame:
        """CSV 파일에서 일봉 데이터를 로드한다.

        Args:
            file_path: CSV 파일 경로

        Returns:
            일봉 데이터 DataFrame

        Raises:
            FileNotFoundError: 파일이 존재하지 않을 때
            ValueError: 필수 컬럼이 누락되었을 때
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {path}")

        logger.info("CSV 파일에서 데이터 로드: %s", path)
        df = pd.read_csv(path)

        return self._validate_dataframe(df)

    async def from_api(
        self,
        stock_code: str,
        days: int = 100,
        client: KISClient | None = None,
    ) -> pd.DataFrame:
        """KIS API에서 일봉 데이터를 조회한다.

        Args:
            stock_code: 종목코드 (6자리)
            days: 조회할 일수 (기본 100일)
            client: KIS API 클라이언트 (미지정 시 새로 생성)

        Returns:
            일봉 데이터 DataFrame
        """
        if client is None:
            client = KISClient()

        quote_api = QuoteAPI(client)
        logger.info("API에서 일봉 데이터 조회: 종목=%s, 일수=%d", stock_code, days)

        items = await quote_api.get_daily_price(stock_code)

        # API는 최신 날짜가 먼저 오므로 역순 정렬
        items = list(reversed(items))

        # days 만큼만 최근 데이터 사용
        if len(items) > days:
            items = items[-days:]

        records = [
            {
                "date": item.date,
                "open": item.open_price,
                "high": item.high_price,
                "low": item.low_price,
                "close": item.close_price,
                "volume": item.volume,
            }
            for item in items
        ]

        df = pd.DataFrame(records)
        return self._validate_dataframe(df)

    def _validate_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame의 유효성을 검증하고 정규화한다.

        필수 컬럼 존재 여부를 확인하고, 날짜 오름차순 정렬 및
        숫자 컬럼의 타입을 int로 변환한다.

        Args:
            df: 검증할 DataFrame

        Returns:
            정규화된 DataFrame

        Raises:
            ValueError: 필수 컬럼이 누락되었을 때
        """
        missing_columns = set(self.REQUIRED_COLUMNS) - set(df.columns)
        if missing_columns:
            raise ValueError(
                f"필수 컬럼이 누락되었습니다: {sorted(missing_columns)}"
            )

        df = df.sort_values("date", ascending=True)

        numeric_columns = ("open", "high", "low", "close", "volume")
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(int)

        df = df.reset_index(drop=True)

        return df
