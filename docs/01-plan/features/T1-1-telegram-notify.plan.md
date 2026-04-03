# [Plan] T1-1 Telegram 알림

## 메타데이터
- 로드맵 ID: T1-1
- 작성일: 2026-04-03
- 우선순위: critical
- 의존성: 없음
- 후속 의존: T2-3(알림 레벨 분류), T2-4(Telegram 원격 명령)

## 목표

매수/매도 체결, 손절, 에러, 일일 결산 등 주요 이벤트를 Telegram으로 즉시 알림 전송.
모니터 없는 홈서버 운영 시 문제를 즉시 인지하기 위한 핵심 기능.

## 알림 이벤트 목록

| 이벤트 | 시점 | 긴급도 | 메시지 예시 |
|--------|------|--------|------------|
| 매수 체결 | 주문 체결 직후 | 일반 | `[매수] 삼성전자(005930) 10주 @ 72,000원` |
| 매도 체결 | 주문 체결 직후 | 일반 | `[매도] SK하이닉스(000660) 5주 @ 185,000원 (익절)` |
| 손절 매도 | 손절 트리거 시 | 긴급 | `[손절] LG에너지솔루션(373220) -3.2% 손절 실행` |
| 일일 결산 | post_market 완료 시 | 일반 | `[결산] 2026-04-03 체결 3건, 손익 +15,200원 (+0.3%)` |
| 시스템 에러 | 예외 발생 시 | 긴급 | `[에러] API 토큰 갱신 실패: ConnectionError` |
| 서비스 시작/종료 | main.py 시작/종료 시 | 일반 | `[시작] 자동매매 시스템 가동 (08:30)` |
| 일일 한도 초과 | DailyLimitExceeded 시 | 긴급 | `[경고] API 일일 한도 초과, 매매 중단` |

## 신규 파일 구조

```
src/notify/
├── __init__.py
├── telegram.py        # TelegramNotifier 클래스
└── formatter.py       # 메시지 포맷팅 함수
```

## 환경변수 추가 (.env)

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ENABLED=true
```

## 기존 코드 연동 포인트

| 위치 | 연동 방법 |
|------|-----------|
| `src/engine.py` `_execute_buy()` | 매수 체결 후 알림 |
| `src/engine.py` `_execute_sell()` | 매도/손절 체결 후 알림 |
| `src/engine.py` `post_market()` | 일일 결산 알림 |
| `src/engine.py` `run_trading_cycle()` | 일일 한도 초과 알림 |
| `main.py` | 서비스 시작/종료 알림 |

## 설계 원칙

1. **알림 실패가 매매에 영향 주지 않을 것**: 모든 알림 전송은 try-except로 감싸고, 실패 시 로그만 남김
2. **비동기 전송**: httpx AsyncClient 사용 (이미 프로젝트 의존성에 포함)
3. **TELEGRAM_ENABLED=false로 알림 비활성화 가능**: 테스트/디버깅 시 편의
4. **후속 확장 고려**: T2-3(알림 레벨), T2-4(원격 명령)를 위해 Notifier를 추상화할 필요 없이, Telegram 전용으로 단순하게 구현. 확장 시 리팩토링.

## 안전 게이트 확인

- `.env` 수정: 수동으로 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 추가 필요 (자동 파이프라인 금지 영역)
- 외부 패키지 추가: 없음 (httpx 이미 사용 중, Telegram Bot API는 HTTP POST로 직접 호출)
- 변경 파일 5개 이내: 신규 3개 + 기존 2개 (engine.py, main.py) = 5개

## 테스트 계획

- `tests/test_notify/test_telegram.py`: TelegramNotifier 단위 테스트 (HTTP 모킹)
- `tests/test_notify/test_formatter.py`: 메시지 포맷팅 테스트
- 기존 engine 테스트가 깨지지 않는 것 확인

## 완료 기준

- [ ] Telegram 메시지가 실제로 수신됨 (수동 확인)
- [ ] 알림 실패 시 매매 로직에 영향 없음
- [ ] 기존 테스트 전부 통과
- [ ] 신규 테스트 통과
