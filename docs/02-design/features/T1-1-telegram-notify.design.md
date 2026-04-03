# [Design] T1-1 Telegram 알림

## 참조
- Plan: `docs/01-plan/features/T1-1-telegram-notify.plan.md`
- 로드맵: `docs/plans/feature-roadmap.md` (T1-1)

---

## 1. 설정 추가 (config.py)

```python
@dataclass(frozen=True)
class TelegramConfig:
    """Telegram 알림 설정."""

    bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))
    enabled: bool = field(
        default_factory=lambda: _env("TELEGRAM_ENABLED", "false").lower() == "true"
    )
```

`Settings` 클래스에 `telegram: TelegramConfig` 필드 추가.

---

## 2. 신규 파일: src/notify/__init__.py

```python
"""알림 모듈."""
```

---

## 3. 신규 파일: src/notify/telegram.py

### TelegramNotifier 클래스

```python
class TelegramNotifier:
    """Telegram Bot API를 통해 알림을 전송한다."""

    SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self) -> None:
        self._token = settings.telegram.bot_token
        self._chat_id = settings.telegram.chat_id
        self._enabled = settings.telegram.enabled

    async def send(self, message: str) -> None:
        """메시지를 전송한다. 실패해도 예외를 전파하지 않는다."""
        if not self._enabled:
            return
        if not self._token or not self._chat_id:
            logger.warning("Telegram 설정 미완료, 알림 스킵")
            return
        try:
            url = self.SEND_MESSAGE_URL.format(token=self._token)
            payload = {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    logger.warning("Telegram 전송 실패: %d", response.status_code)
        except Exception:
            logger.exception("Telegram 알림 전송 중 에러 (매매에 영향 없음)")

    # 편의 메서드
    async def notify_buy(self, stock_name: str, stock_code: str, quantity: int, price: int) -> None:
    async def notify_sell(self, stock_name: str, stock_code: str, quantity: int, price: int, reason: str) -> None:
    async def notify_daily_summary(self, date: str, count: int, profit_loss: int, rate: float) -> None:
    async def notify_error(self, context: str, error: str) -> None:
    async def notify_system(self, message: str) -> None:
```

### 설계 포인트

- `send()`는 절대 예외를 전파하지 않음 (try-except 내부 처리)
- `_enabled=False`면 HTTP 요청 자체를 하지 않음
- `httpx.AsyncClient`를 매 호출마다 생성 (알림 빈도가 낮으므로 커넥션풀 불필요)
- `parse_mode="HTML"` 사용: `<b>`, `<code>` 등으로 가독성 확보

---

## 4. 신규 파일: src/notify/formatter.py

### 포맷팅 함수

```python
def format_buy(stock_name: str, stock_code: str, quantity: int, price: int) -> str:
    """매수 체결 알림 메시지."""
    return (
        f"<b>[매수]</b> {stock_name}({stock_code})\n"
        f"{quantity}주 @ {price:,}원"
    )

def format_sell(stock_name: str, stock_code: str, quantity: int, price: int, reason: str) -> str:
    """매도 체결 알림 메시지."""
    tag = "손절" if reason == "손절" else "매도"
    emoji_prefix = "🔴" if reason == "손절" else "🟢"  # 손절만 빨간색
    return (
        f"{emoji_prefix} <b>[{tag}]</b> {stock_name}({stock_code})\n"
        f"{quantity}주 @ {price:,}원\n"
        f"사유: {reason}"
    )

def format_daily_summary(date: str, count: int, profit_loss: int, rate: float) -> str:
    """일일 결산 알림 메시지."""
    sign = "+" if profit_loss >= 0 else ""
    return (
        f"<b>[결산]</b> {date}\n"
        f"체결: {count}건\n"
        f"손익: {sign}{profit_loss:,}원 ({sign}{rate:.2f}%)"
    )

def format_error(context: str, error: str) -> str:
    """에러 알림 메시지."""
    return (
        f"🚨 <b>[에러]</b> {context}\n"
        f"<code>{error[:200]}</code>"  # 에러 메시지 200자 제한
    )

def format_system(message: str) -> str:
    """시스템 알림 메시지."""
    return f"<b>[시스템]</b> {message}"
```

---

## 5. 기존 파일 변경: src/engine.py

### 5-1. __init__에 notifier 추가

```python
from src.notify.telegram import TelegramNotifier

class TradingEngine:
    def __init__(self, ...) -> None:
        ...
        self._notifier = TelegramNotifier()
```

### 5-2. _execute_buy() — 매수 체결 알림

```python
async def _execute_buy(self, stock_code, stock_name, quantity, price) -> None:
    try:
        result = await self._order.buy(...)
        ...
        logger.info("[매수 체결] ...")
        self._record_order_to_db(...)

        # Telegram 알림
        await self._notifier.notify_buy(stock_name, stock_code, quantity, price)

    except Exception:
        logger.exception("[매수 실패] ...")
```

### 5-3. _execute_sell() — 매도/손절 알림

```python
async def _execute_sell(self, stock_code, quantity, price, reason="") -> None:
    try:
        result = await self._order.sell(...)
        ...
        logger.info("[매도 체결] ...")
        self._record_order_to_db(...)

        # Telegram 알림
        await self._notifier.notify_sell("", stock_code, quantity, price, reason)

    except Exception:
        logger.exception("[매도 실패] ...")
```

### 5-4. post_market() — 일일 결산 알림

```python
async def post_market(self) -> None:
    ...
    self._create_calendar_event(balance, executions)

    # Telegram 일일 결산 알림
    await self._notifier.notify_daily_summary(
        date=date.today().isoformat(),
        count=len(executions),
        profit_loss=int(balance.total_profit_loss),
        rate=float(balance.total_profit_rate),
    )
    ...
```

### 5-5. run_trading_cycle() — 일일 한도 초과 알림

한도 초과 시 `_daily_limit_reached` 플래그를 설정하는 3곳에서:
```python
self._daily_limit_reached = True
logger.warning("API 일일 한도 초과, 당일 매매 사이클 중단")
await self._notifier.notify_error("장중 매매", "API 일일 한도 초과, 당일 매매 사이클 중단")
return
```

---

## 6. 기존 파일 변경: main.py

```python
from src.notify.telegram import TelegramNotifier

async def main() -> None:
    notifier = TelegramNotifier()
    ...
    await notifier.notify_system(
        f"자동매매 시스템 가동 ({settings.kis.env})"
    )
    ...
    try:
        await stop_event.wait()
    finally:
        await notifier.notify_system("자동매매 시스템 종료")
        scheduler.shutdown()
```

---

## 7. 구현 순서

1. `src/config.py` — TelegramConfig 추가
2. `src/notify/__init__.py` — 모듈 생성
3. `src/notify/formatter.py` — 포맷팅 함수
4. `src/notify/telegram.py` — TelegramNotifier 클래스
5. `tests/test_notify/test_formatter.py` — 포맷팅 테스트
6. `tests/test_notify/test_telegram.py` — Notifier 테스트 (HTTP 모킹)
7. `src/engine.py` — 알림 연동
8. `main.py` — 시작/종료 알림

---

## 8. 테스트 설계

### test_formatter.py

```python
class TestFormatter:
    def test_format_buy(self) -> None:
        result = format_buy("삼성전자", "005930", 10, 72000)
        assert "[매수]" in result
        assert "72,000" in result

    def test_format_sell_stop_loss(self) -> None:
        result = format_sell("SK하이닉스", "000660", 5, 185000, "손절")
        assert "[손절]" in result

    def test_format_daily_summary_positive(self) -> None:
        result = format_daily_summary("2026-04-03", 3, 15200, 0.3)
        assert "+15,200" in result

    def test_format_daily_summary_negative(self) -> None:
        result = format_daily_summary("2026-04-03", 1, -5000, -0.1)
        assert "-5,000" in result

    def test_format_error_truncates(self) -> None:
        result = format_error("테스트", "a" * 300)
        assert len(result) < 350  # 200자 제한 확인
```

### test_telegram.py

```python
class TestTelegramNotifier:
    async def test_send_disabled(self) -> None:
        """enabled=False면 HTTP 요청하지 않는다."""

    async def test_send_success(self, httpx_mock) -> None:
        """정상 전송 시 200 응답."""

    async def test_send_failure_no_exception(self, httpx_mock) -> None:
        """전송 실패해도 예외가 전파되지 않는다."""

    async def test_send_missing_token(self) -> None:
        """토큰 미설정 시 경고 로그만 남긴다."""
```

---

## 9. 변경 파일 요약

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `src/config.py` | 수정 | TelegramConfig 추가 |
| `src/notify/__init__.py` | 신규 | 모듈 초기화 |
| `src/notify/formatter.py` | 신규 | 메시지 포맷팅 함수 7개 |
| `src/notify/telegram.py` | 신규 | TelegramNotifier 클래스 |
| `src/engine.py` | 수정 | 알림 연동 (4곳) |
| `main.py` | 수정 | 시작/종료 알림 |
| `tests/test_notify/test_formatter.py` | 신규 | 포맷팅 테스트 |
| `tests/test_notify/test_telegram.py` | 신규 | Notifier 테스트 |
