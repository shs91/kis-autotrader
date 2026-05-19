"""KIS 종목마스터 다운로드 + 파싱 + sync.

KIS의 공개 종목마스터 파일을 일일 1회 다운로드해 거래정지/관리종목/정리매매/
시장경고/경고예고/불성실공시 6개 플래그를 `market_actions` 테이블에 sync한다.

매매 엔진은 매수 직전 `MarketActionRepository.is_blocked(code)`로 차단.

파일 spec: KIS open-trading-api 저장소의 stocks_info/kis_kospi_code_mst.py와
kis_kosdaq_code_mst.py 패턴 그대로 (cp949, 고정 길이 컬럼).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from src.db.models import MarketAction
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.db.repository import MarketActionRepository, StockRepository

logger = setup_logger(__name__)

KOSPI_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
KOSDAQ_URL = "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip"

# part2 너비 (마지막 N 바이트). KOSPI=228, KOSDAQ=222.
KOSPI_PART2_WIDTH = 228
KOSDAQ_PART2_WIDTH = 222


class MasterMarket(Enum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


@dataclass(frozen=True)
class MasterRow:
    """KIS 종목마스터 한 행의 핵심 필드만 추출."""

    stock_code: str
    name: str
    market: MasterMarket
    is_trading_halted: bool
    is_administrative: bool
    is_liquidation: bool
    is_market_warning: bool
    is_warning_pretrigger: bool
    is_dishonest_disclosure: bool


@dataclass
class MasterSyncResult:
    """sync 사이클 결과 요약."""

    total_rows: int
    market_actions_upserted: int
    stocks_inserted: int
    elapsed_ms: int = 0


def download_master_zip(
    market: MasterMarket,
    dest_dir: Path,
    client: httpx.Client | None = None,
) -> Path:
    """KIS 종목마스터 zip을 받아 .mst 파일을 추출하고 그 경로를 반환.

    Args:
        market: KOSPI 또는 KOSDAQ.
        dest_dir: 추출 디렉토리. 없으면 생성.
        client: httpx.Client (테스트용 주입). 없으면 새로 생성.

    Returns: 추출된 .mst 파일 경로 (예: dest_dir/kospi_code.mst).
    """
    url = KOSPI_URL if market == MasterMarket.KOSPI else KOSDAQ_URL
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"{market.value.lower()}_code.mst.zip"

    own_client = client is None
    c = client or httpx.Client(timeout=httpx.Timeout(30.0))
    try:
        response = c.get(url)
        response.raise_for_status()
        zip_path.write_bytes(response.content)
    finally:
        if own_client:
            c.close()

    with zipfile.ZipFile(zip_path) as zf:
        # 보통 단일 .mst 파일만 들어있음
        members = [m for m in zf.namelist() if m.endswith(".mst")]
        if not members:
            raise RuntimeError(f"{market.value} zip에 .mst 파일이 없음")
        zf.extract(members[0], dest_dir)
        extracted = dest_dir / members[0]

    zip_path.unlink(missing_ok=True)
    logger.info("KIS 종목마스터 다운로드 완료: %s", extracted)
    return extracted


def parse_master_file(path: Path, market: MasterMarket) -> list[MasterRow]:
    """cp949 마스터 파일을 파싱해 MasterRow 리스트 반환.

    KIS open-trading-api 저장소의 파싱 패턴(line slicing)을 그대로 따른다.
    """
    part2_width = (
        KOSPI_PART2_WIDTH if market == MasterMarket.KOSPI else KOSDAQ_PART2_WIDTH
    )

    rows: list[MasterRow] = []
    with path.open(encoding="cp949") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if len(line) <= part2_width:
                continue
            # part1: row[:len-part2_width], part2: row[-part2_width:]
            part1 = line[: len(line) - part2_width]
            part2 = line[-part2_width:]

            stock_code = part1[0:9].rstrip()
            name = part1[21:].strip()
            if not stock_code:
                continue

            # 일반 주식 종목코드는 6자리 숫자(KOSPI/KOSDAQ 동일).
            # F-prefix(파생/ELW) · 9자리 영문 코드 등은 매매 대상이 아니므로 제외.
            if not (len(stock_code) == 6 and stock_code.isdigit()):
                continue

            # 그룹코드 필터 — 'ST'(주식)만 통과. EF=ETF, EN=ETN, EW=ELW, ...
            # part2의 첫 2자가 그룹코드여야 하나, 실제 마스터 파일은 한글명 패딩
            # 때문에 part2 시작에 공백 1자가 추가됨(`' ST...'`). lstrip으로 흡수.
            group_code = part2.lstrip()[:2]
            if group_code != "ST":
                continue

            offsets = _status_offsets(market)
            halted = part2[offsets[0] : offsets[0] + 1].strip()
            liquidation = part2[offsets[1] : offsets[1] + 1].strip()
            administrative = part2[offsets[2] : offsets[2] + 1].strip()
            warning_code = part2[offsets[3] : offsets[3] + 2].strip()
            pretrigger = part2[offsets[4] : offsets[4] + 1].strip()
            dishonest = part2[offsets[5] : offsets[5] + 1].strip()

            rows.append(MasterRow(
                stock_code=stock_code,
                name=name,
                market=market,
                is_trading_halted=halted == "Y",
                is_administrative=administrative == "Y",
                is_liquidation=liquidation == "Y",
                # 시장경고는 코드: "00"이면 정상, 그 외 (01/02/03)는 경고/위험.
                is_market_warning=bool(warning_code) and warning_code != "00",
                is_warning_pretrigger=pretrigger == "Y",
                is_dishonest_disclosure=dishonest == "Y",
            ))
    logger.info(
        "KIS 종목마스터 파싱 완료: %s, %d 종목", market.value, len(rows),
    )
    return rows


def _status_offsets(market: MasterMarket) -> tuple[int, int, int, int, int, int]:
    """part2 안에서 (거래정지, 정리매매, 관리종목, 시장경고, 경고예고, 불성실)
    각 컬럼의 시작 offset.

    실측: KIS 마스터 파일의 실제 구조에서 part2 시작에 공백 1자 패딩이 들어가
    KIS field_specs 누적값(60)보다 1자 뒤로 이동(61). 005930(삼성전자) 라인의
    part2[61]='N' 거래정지, part2[64:66]='00' 시장경고로 검증함.
    """
    base = 61
    return (
        base,        # 거래정지(1)
        base + 1,    # 정리매매(1)
        base + 2,    # 관리종목(1)
        base + 3,    # 시장경고(2)
        base + 5,    # 경고예고(1)
        base + 6,    # 불성실공시(1)
    )


class MasterSyncer:
    """파싱된 MasterRow를 stocks/market_actions에 sync."""

    def __init__(
        self,
        market_action_repo: MarketActionRepository,
        stock_repo: StockRepository,
    ) -> None:
        self._ma_repo = market_action_repo
        self._stock_repo = stock_repo

    def sync(
        self,
        rows: list[MasterRow],
        snapshot_at: datetime,
    ) -> MasterSyncResult:
        if not rows:
            return MasterSyncResult(
                total_rows=0, market_actions_upserted=0, stocks_inserted=0,
            )

        # 1) stocks upsert (신규 종목만 insert — 기존은 그대로 두어 매매 이력 보호)
        stocks_inserted = 0
        for row in rows:
            if self._stock_repo.get_by_code(row.stock_code) is None:
                self._stock_repo.create(
                    code=row.stock_code,
                    name=row.name,
                    market=row.market.value,
                )
                stocks_inserted += 1

        # 2) market_actions upsert (전체)
        actions = [
            MarketAction(
                stock_code=row.stock_code,
                is_trading_halted=row.is_trading_halted,
                is_administrative=row.is_administrative,
                is_liquidation=row.is_liquidation,
                is_market_warning=row.is_market_warning,
                is_warning_pretrigger=row.is_warning_pretrigger,
                is_dishonest_disclosure=row.is_dishonest_disclosure,
                snapshot_at=snapshot_at,
            )
            for row in rows
        ]
        upserted = self._ma_repo.upsert(actions)

        return MasterSyncResult(
            total_rows=len(rows),
            market_actions_upserted=upserted,
            stocks_inserted=stocks_inserted,
        )
