#!/usr/bin/env python
"""KIS 종목마스터 일일 sync 스크립트.

KOSPI/KOSDAQ 마스터 zip을 다운로드해 stocks/market_actions 테이블을 갱신한다.
launchd 일일 잡(장 마감 후 17:00 KST 권장)으로 실행.

사용:
    .venv/bin/python scripts/sync_market_master.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트를 path에 추가 (scripts/ 서브디렉토리에서 실행 시)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.db.repository import MarketActionRepository, StockRepository  # noqa: E402
from src.db.session import get_session  # noqa: E402
from src.market_master import (  # noqa: E402
    MasterMarket,
    MasterSyncer,
    download_master_zip,
    parse_master_file,
)
from src.utils.logger import setup_logger  # noqa: E402

load_dotenv()
logger = setup_logger(__name__)


def main() -> int:
    snapshot_at = datetime.now(UTC)
    totals = {"rows": 0, "actions": 0, "stocks": 0}

    with tempfile.TemporaryDirectory(prefix="kis_master_") as tmp:
        tmp_dir = Path(tmp)
        for market in (MasterMarket.KOSPI, MasterMarket.KOSDAQ):
            try:
                mst_path = download_master_zip(market, dest_dir=tmp_dir)
                rows = parse_master_file(mst_path, market)
            except Exception as e:  # noqa: BLE001 — 시장 단위 격리
                logger.exception(
                    "%s 마스터 다운로드/파싱 실패: %s", market.value, e,
                )
                continue

            with get_session() as session:
                syncer = MasterSyncer(
                    market_action_repo=MarketActionRepository(session),
                    stock_repo=StockRepository(session),
                )
                result = syncer.sync(rows=rows, snapshot_at=snapshot_at)
            totals["rows"] += result.total_rows
            totals["actions"] += result.market_actions_upserted
            totals["stocks"] += result.stocks_inserted
            logger.info(
                "%s sync 완료: rows=%d, actions=%d, new_stocks=%d",
                market.value, result.total_rows,
                result.market_actions_upserted, result.stocks_inserted,
            )

    logger.info(
        "전체 sync 완료: total_rows=%d, actions=%d, new_stocks=%d",
        totals["rows"], totals["actions"], totals["stocks"],
    )
    return 0 if totals["rows"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
