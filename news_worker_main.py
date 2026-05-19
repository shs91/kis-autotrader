"""NewsCollectorWorker 엔트리포인트.

별도 launchd 서비스(com.kis.news-collector)로 실행한다 — 매매 메인 프로세스와
메모리/실패 격리. .env 로딩은 src.config 패턴 그대로.

실행:
    .venv/bin/python news_worker_main.py
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.db.repository import NewsChunkRepository, StockRepository
from src.db.session import get_session
from src.rag.embedder import Embedder
from src.rag.ticker_matcher import TickerMatcher
from src.utils.logger import setup_logger
from src.worker.collectors.base import BaseCollector
from src.worker.collectors.dart import DARTCollector
from src.worker.collectors.rss import FeedSource, RSSCollector
from src.worker.news_collector import NewsCollectorWorker

load_dotenv()
logger = setup_logger(__name__)


def _load_corp_code_map(path: str | None) -> dict[str, str]:
    """DART corp_code.xml 파일을 파싱해 corp_code → stock_code 매핑을 반환.

    파일은 https://opendart.fss.or.kr/api/corpCode.xml zip을 풀어서 얻는다.
    파일이 없으면 빈 dict (수집 대상 0) — 운영자가 setup하기 전까지 안전 fallback.
    """
    if not path or not Path(path).exists():
        logger.warning(
            "DART corp_code 파일 없음 (%s) — DART 수집 비활성",
            path,
        )
        return {}
    import xml.etree.ElementTree as ET  # noqa: S405 — 신뢰된 DART 공식 파일
    mapping: dict[str, str] = {}
    tree = ET.parse(path)  # noqa: S314 — DART 공식 corp_code.xml은 신뢰 영역
    for elem in tree.iter("list"):
        corp_code = (elem.findtext("corp_code") or "").strip()
        stock_code = (elem.findtext("stock_code") or "").strip()
        if corp_code and stock_code:
            mapping[corp_code] = stock_code
    logger.info("DART corp_code 매핑 로드: %d 종목", len(mapping))
    return mapping


def _build_ticker_matcher() -> TickerMatcher:
    with get_session() as session:
        stocks = StockRepository(session).list_all()
        pairs = [(s.code, s.name) for s in stocks]
    logger.info("TickerMatcher 사전 로드: %d 종목", len(pairs))
    return TickerMatcher(pairs)


def _load_rss_feeds(path: str | None) -> list[FeedSource]:
    """JSON 설정 파일에서 RSS 피드 목록을 로드.

    파일 형식: `config/rss_feeds.example.json` 참조.
    파일 없으면 빈 리스트 (RSS 비활성) — 안전 fallback.
    """
    if not path or not Path(path).exists():
        logger.warning("RSS 설정 파일 없음 (%s) — RSS 수집 비활성", path)
        return []
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    feeds_data = data.get("feeds") or []
    feeds = [
        FeedSource(
            label=item["label"],
            category=item["category"],
            provider=item["provider"],
            url=item["url"],
        )
        for item in feeds_data
    ]
    logger.info("RSS 피드 로드: %d개", len(feeds))
    return feeds


def _build_collectors(
    embedder: Embedder,
    repo: NewsChunkRepository,
) -> list[BaseCollector]:
    collectors: list[BaseCollector] = []

    dart_key = os.getenv("NEWS_DART_API_KEY", "").strip()
    corp_code_path = os.getenv("NEWS_DART_CORP_CODE_PATH", "data/dart/corp_code.xml")
    if dart_key:
        corp_code_map = _load_corp_code_map(corp_code_path)
        if corp_code_map:
            collectors.append(DARTCollector(
                embedder=embedder,
                repo=repo,
                api_key=dart_key,
                corp_code_to_ticker=corp_code_map,
                rate_limit_sec=float(os.getenv("NEWS_DART_RATE_LIMIT_PER_SEC", "1.0")),
            ))
    else:
        logger.warning("NEWS_DART_API_KEY 미설정 — DART 수집 비활성")

    rss_config_path = os.getenv("NEWS_RSS_CONFIG_PATH", "config/rss_feeds.json")
    feeds = _load_rss_feeds(rss_config_path)
    if feeds:
        matcher = _build_ticker_matcher()
        collectors.append(RSSCollector(
            embedder=embedder,
            repo=repo,
            feeds=feeds,
            ticker_matcher=matcher,
            user_agent=os.getenv(
                "NEWS_RSS_USER_AGENT", "kis-autotrader/0.1",
            ),
        ))

    return collectors


async def _main() -> int:
    embedder = Embedder.get()  # 5초 워밍업
    with get_session() as session:
        repo = NewsChunkRepository(session)
        collectors = _build_collectors(embedder, repo)
        if not collectors:
            logger.error("활성 collector 없음 — 종료")
            return 1

        interval = float(os.getenv("NEWS_COLLECT_INTERVAL_MIN", "5")) * 60
        worker = NewsCollectorWorker(
            collectors=collectors, interval_sec=interval,
        )

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _on_signal(*_: object) -> None:
            logger.info("종료 시그널 수신 — 그레이스풀 종료")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal)

        run_task = asyncio.create_task(worker.run())
        stop_task = asyncio.create_task(stop_event.wait())
        await asyncio.wait({run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
