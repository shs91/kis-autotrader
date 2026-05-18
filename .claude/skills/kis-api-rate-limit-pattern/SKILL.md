---
name: kis-api-rate-limit-pattern
description: KIS API 호출 제한 규칙과 WebSocket 상태 머신 준수 패턴. RateLimiter 사용 + 재연결 backoff + 디바운싱.
---

# KIS API Rate Limit Pattern

## 핵심 규칙
- **REST**: 초당 5건(virtual) / 20건(real). Token Bucket `src.api.rate_limiter`를 반드시 경유.
- **WebSocket**: 연결 → 구독 → 데이터 수신 확인 → 구독 해제 → 종료. 패턴 위반 시 IP/앱키 차단.
- **재연결**: exponential backoff 5→10→20→60초, 최대 5회.
- **Circuit Breaker**: 연속 5회 실패 시 트립, 30→60→120→240→300초 대기.

## 코드 패턴
```python
# 올바른 REST 호출
async with rate_limiter.acquire():
    response = await client.get(url, headers=headers)

# 올바른 WS 패턴
await ws.connect()
await ws.subscribe(symbol)
data = await ws.recv()  # 수신 확인
await ws.unsubscribe(symbol)  # 디바운싱: 최소 1초 간격
await ws.close()
```

## 금지 패턴
- RateLimiter 우회한 직접 httpx 호출
- WS 연결 직후 즉시 종료 반복
- 구독 등록/해제 무한 반복 (디바운싱 위반)

## 검증
구현 후 `pytest tests/test_api/test_rate_limiter.py tests/test_api/test_websocket.py`로 회귀 확인.
