"""긴급 알림 전송 실패 시 파일 폴백 테스트(치명 알림 소실 방지)."""

from __future__ import annotations

import pytest

from src.notify import telegram as tg


class _FailingClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FailingClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("network down")


@pytest.fixture
def notifier() -> tg.TelegramNotifier:
    n = tg.TelegramNotifier()
    n._enabled = True
    n._token = "test-token"  # noqa: S105 (테스트용 더미 토큰)
    n._chat_id = "test-chat"
    return n


@pytest.mark.asyncio
async def test_urgent_failure_writes_fallback(
    tmp_path, monkeypatch, notifier: tg.TelegramNotifier
) -> None:
    fallback = tmp_path / "urgent.log"
    monkeypatch.setattr(tg, "URGENT_FALLBACK_FILE", str(fallback))
    monkeypatch.setattr(tg.httpx, "AsyncClient", _FailingClient)

    await notifier.send("긴급: 손절 실패", urgent=True)

    assert fallback.exists()
    assert "긴급: 손절 실패" in fallback.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_non_urgent_failure_no_fallback(
    tmp_path, monkeypatch, notifier: tg.TelegramNotifier
) -> None:
    fallback = tmp_path / "urgent.log"
    monkeypatch.setattr(tg, "URGENT_FALLBACK_FILE", str(fallback))
    monkeypatch.setattr(tg.httpx, "AsyncClient", _FailingClient)

    await notifier.send("일반 알림", urgent=False)

    assert not fallback.exists()


@pytest.mark.asyncio
async def test_unconfigured_urgent_writes_fallback(
    tmp_path, monkeypatch
) -> None:
    fallback = tmp_path / "urgent.log"
    monkeypatch.setattr(tg, "URGENT_FALLBACK_FILE", str(fallback))
    n = tg.TelegramNotifier()
    n._enabled = True
    n._token = ""  # 미설정
    n._chat_id = ""

    await n.send("긴급: 설정 누락", urgent=True)

    assert fallback.exists()
    assert "긴급: 설정 누락" in fallback.read_text(encoding="utf-8")
