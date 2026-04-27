# Cowork ↔ Claude Code 자동화 파이프라인 규격

> Cowork(분석/기획)가 제안서를 작성하면 Claude Code(구현)가 자동으로 구현합니다.
> 사람의 승인 없이 동작하므로, 자동 검증 게이트로 안전성을 확보합니다.

## 디렉토리 구조

```
docs/
├── BRIDGE_SPEC.md              ← 이 파일 (규격 정의)
├── proposals/                  ← Cowork가 작성 → Claude Code가 자동 구현
│   ├── YYYY-MM-DD_제목.md
│   └── ...
├── reports/                    ← Cowork가 작성하는 분석 리포트
│   ├── YYYY-MM-DD_daily.md
│   └── YYYY-WNN_weekly.md
└── CHANGELOG.md                ← Claude Code가 기록하는 변경 이력
```

## 제안서 상태 흐름 (완전 자동)

```
Cowork 작성 → ready → Claude Code 구현 시도
                         ├─ 테스트 pass → implemented
                         └─ 테스트 fail → failed (Cowork가 다음 날 재분석)
```

- `ready`: Cowork가 작성 완료. Claude Code가 즉시 구현 가능.
- `implemented`: 구현 + 테스트 통과 + 프로세스 재시작 완료.
- `failed`: 테스트 실패. 실패 사유 포함. Cowork가 다음 분석에서 재검토.
- `skipped`: 안전 규칙 위반으로 자동 스킵됨.

## 자동 안전 게이트

Claude Code는 제안서를 구현하기 전에 아래 규칙을 자동 검증합니다.
**하나라도 위반하면 `skipped` 상태로 변경하고 구현하지 않습니다.**

### 금지 영역 (절대 자동 변경 불가)

| 항목 | 사유 |
|------|------|
| `.env` 파일 수정 | API 키, DB 비밀번호 등 민감 정보 |
| `credentials.json`, `token.json` | Google OAuth 인증 정보 |
| `KIS_ENV` 값 변경 (virtual → real) | 모의→실전 전환은 반드시 수동 |
| `alembic/versions/` 마이그레이션 생성 | DB 스키마 변경은 수동 검토 필요 |
| 외부 패키지 추가 (`pyproject.toml` dependencies) | 의존성 추가는 수동 검토 필요 |

### 파라미터 변경 허용 범위

> 변경 방식: `config_overrides.json` 파일을 통한 오버라이드.
> `.env` 파일은 직접 수정 금지 (금지 영역 유지).

| 파라미터 | .env 키 | 현재값 | 자동 변경 허용 범위 |
|----------|---------|--------|---------------------|
| MAX_LOSS_RATE | MAX_LOSS_RATE | 0.03 | 0.01 ~ 0.05 |
| MAX_POSITION_RATIO | MAX_POSITION_RATIO | 0.2 | 0.05 ~ 0.3 |
| DAILY_TRADE_LIMIT | DAILY_TRADE_LIMIT | 200 | 50 ~ 500 |
| TAKE_PROFIT_RATIO | TAKE_PROFIT_RATIO | 0.05 | 0.02 ~ 0.10 |
| MA short_period | STRATEGY_MA_SHORT_PERIOD | 5 | 3 ~ 10 |
| MA long_period | STRATEGY_MA_LONG_PERIOD | 20 | 15 ~ 60 |
| MA max_divergence | STRATEGY_MA_MAX_DIVERGENCE | 0.05 | 0.01 ~ 0.15 |
| RSI period | STRATEGY_RSI_PERIOD | 14 | 7 ~ 21 |
| RSI oversold | STRATEGY_RSI_OVERSOLD | 30.0 | 20.0 ~ 40.0 |
| RSI overbought | STRATEGY_RSI_OVERBOUGHT | 70.0 | 60.0 ~ 80.0 |
| MIN_CONFIDENCE | STRATEGY_MIN_CONFIDENCE | 0.1 | 0.05 ~ 0.5 |
| MAX_DAILY_DRAWDOWN | MAX_DAILY_DRAWDOWN | 0.08 | 0.03 ~ 0.15 |
| MAX_CONSECUTIVE_LOSSES | MAX_CONSECUTIVE_LOSSES | 7 | 3 ~ 10 |
| SCREENING_TOP_N | SCREENING_TOP_N | 30 | 5 ~ 50 |
| SCREENING_INTERVAL_CYCLES | SCREENING_INTERVAL_CYCLES | 30 | 10 ~ 100 |
| MAX_SCREENED_STOCKS | MAX_SCREENED_STOCKS | 10 | 3 ~ 30 |
| SCREENING_MIN_PRICE | SCREENING_MIN_PRICE | 1000 | 500 ~ 5000 |
| SCREENING_MAX_PRICE | SCREENING_MAX_PRICE | 300000 | 100000 ~ 1000000 |
| SCREENING_CHANGE_RATE_MIN | SCREENING_CHANGE_RATE_MIN | -3.0 | -10.0 ~ 0.0 |
| SCREENING_CHANGE_RATE_MAX | SCREENING_CHANGE_RATE_MAX | 15.0 | 5.0 ~ 30.0 |
| SCREENING_MIN_VOLUME | SCREENING_MIN_VOLUME | 50000 | 10000 ~ 200000 |
| SCREENING_WEIGHT_VOLUME_RANK | SCREENING_WEIGHT_VOLUME_RANK | 0.2 | 0.0 ~ 1.0 |
| SCREENING_WEIGHT_CHANGE_RATE | SCREENING_WEIGHT_CHANGE_RATE | 0.3 | 0.0 ~ 1.0 |
| SCREENING_WEIGHT_STRATEGY | SCREENING_WEIGHT_STRATEGY | 0.5 | 0.0 ~ 1.0 |
| SCREENING_MIN_SCORE | SCREENING_MIN_SCORE | 0.25 | 0.1 ~ 0.8 |

**가중치 제약**: `WEIGHT_VOLUME_RANK + WEIGHT_CHANGE_RATE + WEIGHT_STRATEGY`의 합은 반드시 1.0이어야 한다.
범위를 벗어나거나 가중치 합이 1.0이 아닌 제안서는 `skipped` 처리.

### 파라미터 변경 메커니즘

`.env` 파일은 금지 영역이므로 직접 수정할 수 없다.
파라미터 조정은 `config_overrides.json`을 통해 수행한다.

#### config_overrides.json 규격

경로: `프로젝트 루트/config_overrides.json`

```json
{
  "_meta": {
    "updated_at": "2026-04-09T21:00:00",
    "updated_by": "proposal:2026-04-09_rsi-threshold-tuning"
  },
  "MAX_LOSS_RATE": 0.025,
  "STRATEGY_RSI_OVERSOLD": 25.0,
  "SCREENING_MIN_VOLUME": 80000
}
```

#### 규칙
1. Claude Code는 제안서 구현 시 `.env` 대신 `config_overrides.json`을 생성/수정한다
2. 기존 오버라이드 값이 있으면 덮어쓰고, `_meta`를 갱신한다
3. `config_overrides.json`은 **코드 변경 규칙의 5개 파일 제한에 포함되지 않는다**
4. 롤백 시에는 해당 키를 `config_overrides.json`에서 제거한다

### 코드 변경 규칙

- 기존 함수/클래스의 **시그니처(인자, 반환 타입)** 변경 시 → 관련 테스트가 반드시 같이 수정되어야 함
- **새 파일 생성**은 `src/strategy/`, `tests/` 하위에서만 허용
- **파일 삭제**는 금지 (리팩토링 시에도 기존 파일 유지)
- 한 제안서당 변경 파일 **최대 5개** (너무 큰 변경은 분할 필요)

### 구현 후 필수 검증

```bash
# 1. 전체 테스트 통과 필수
pytest tests/ -q

# 2. 타입 체크 통과 필수
python -m mypy src/

# 3. 린트 통과 필수
ruff check src/
```

세 가지 모두 pass해야 `implemented`. 하나라도 fail이면 변경을 git restore로 원복하고 `failed` 처리.

## 제안서 규격

파일명: `docs/proposals/YYYY-MM-DD_제목.md`

```markdown
# [제안 제목]

## 메타데이터
- 작성: Cowork
- 일자: YYYY-MM-DD
- 상태: ready
- 우선순위: critical | high | medium | low
- 카테고리: param_tuning | refactor | new_strategy | bug_fix | performance
- 관련파일: src/경로/파일.py

## 현상 분석
[데이터 기반 분석 — 로그, 성과 데이터, 에러 패턴 등]

## 제안 내용
[변경 방향과 근거]

## 변경 스펙
[Claude Code가 실행할 구체적 변경 명세]

### 파일별 변경사항
- `src/파일.py`: 변경 전 → 변경 후 (구체적 코드 레벨)

### 추가 테스트 (필요 시)
- 새로 작성할 테스트 케이스 명세

## 기대 효과
[정량적 기대 효과]

## 롤백
[문제 발생 시 원복 방법]
```

## 일일 리포트 규격

파일명: `docs/reports/YYYY-MM-DD_daily.md`

```markdown
# [YYYY-MM-DD] 일일 매매 리포트

## 요약
| 항목 | 값 |
|------|-----|
| 총 매매 | N건 (매수 N / 매도 N) |
| 스크리닝 발굴 | N종목 |
| 에러 | N건 |
| 사이클 실행/스킵 | N / N |

## 체결 내역
| 시각 | 종목 | 구분 | 수량 | 가격 | 사유 |
|------|------|------|------|------|------|

## 전략 시그널 분석
[골든크로스/데드크로스 발생, 신뢰도 분포, 시그널 정확도]

## 에러/경고
| 시각 | 심각도 | 내용 | 추정 원인 |
|------|--------|------|----------|

## 이전 제안서 효과 검증
[implemented 상태인 제안서의 효과를 데이터로 검증]

## 개선 포인트
[제안서 작성이 필요한 항목 — 이 섹션의 내용을 proposals/로 분리 작성]
```

## 주간 리포트 규격

파일명: `docs/reports/YYYY-Www_weekly.md` (예: `2026-W17_weekly.md`)

```markdown
# [YYYY-Www] 주간 매매 리포트

## 주간 요약
| 항목 | 값 |
|------|-----|
| 기간 | YYYY-MM-DD ~ YYYY-MM-DD |
| 총 매매 | N건 (매수 N / 매도 N) |
| 주간 손익 | +/-N원 (수익률 N%) |
| 주간 승률 | N% (N승 / N매도) |
| 스크리닝 전환율 | N% (평균) |
| 에러 | N건 |

## 일별 추이
| 날짜 | 매수 | 매도 | 승률 | 손익 | 누적손익 |
|------|------|------|------|------|----------|

## 종목별 성과
| 종목 | 매매횟수 | 손익 | 비고 |
|------|----------|------|------|

## 전략 평가
### 시그널 전환율
[signal_type별 전환율·confidence 분석]

### 매수 전략별 성과
[buy_reason별 후속 매도 수익률]

## 리스크 분석
### 매도 사유 분포
| 사유 | 건수 | 평균손익률 | 최소 | 최대 | 총손익 |
|------|------|-----------|------|------|--------|

### 스크리닝 효율
[일별 전환율 추이, 주간 평균]

## 시스템 안정성
[에러 추이, API 한도 도달, 재시작 현황]

## 중기 아키텍처 논의
[데이터 기반 구조 개선 논의]

## 다음 주 액션 아이템
- [ ] 항목 1
- [ ] 항목 2
```

## 월간 리포트 규격

파일명: `docs/reports/YYYY-MM_monthly.md` (예: `2026-04_monthly.md`)

```markdown
# [YYYY-MM] 월간 매매 리포트

## 월간 요약
| 항목 | 값 |
|------|-----|
| 거래일수 | N일 |
| 총 매매 | N건 (매수 N / 매도 N) |
| 월간 누적 손익 | +/-N원 (수익률 N%) |
| 월간 승률 | N% |
| 최대 일간 drawdown | -N원 (MM-DD) |
| 시스템 가동률 | N% (cycles_completed / cycles_started) |

## 주차별 추이
| 주차 | 기간 | 매매건수 | 손익 | 평균수익률 |
|------|------|----------|------|-----------|

## 종목 TOP 5 / BOTTOM 5
### 수익 상위
| 종목 | 매매횟수 | 총손익 | 평균수익률 |
|------|----------|--------|-----------|

### 손실 상위
| 종목 | 매매횟수 | 총손익 | 평균수익률 |
|------|----------|--------|-----------|

## 시그널·리스크 평가
### 시그널 정확도
[signal_type별 월간 전환율·confidence 분포]

### 매도 사유 통계
| 사유 | 건수 | 평균 | 중앙값 | 최소 | 최대 | 총손익 |
|------|------|------|--------|------|------|--------|

### 매수 전략별 성과
[buy_reason별 매수 후 실현 수익률 분석]

## 시스템 안정성
[에러 카테고리별 추이, API 한도, 재시작 현황]

## 전략 방향성 판단
[MA 전략 유효성, 리스크 파라미터 적정성, 앙상블 필요성 등]

## 다음 달 액션 아이템
- [ ] 항목 1
- [ ] 항목 2
```

## 분석 쿼리 출력 포맷 (query_analytics.py)

Cowork가 리포트/제안서를 작성할 때 `scripts/query_analytics.py`의 JSON 출력을 파싱합니다.

### daily 커맨드

```bash
python scripts/query_analytics.py daily 2026-04-07
```

```json
{
  "date": "2026-04-07",
  "trades": [
    {
      "id": 1,
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "trade_type": "BUY | SELL",
      "quantity": 10,
      "price": 70000,
      "total_amount": 700000,
      "sell_reason": "STOP_LOSS | TAKE_PROFIT | STRATEGY | MANUAL | null",
      "signal_type": "GOLDEN_CROSS | DEAD_CROSS | null",
      "profit_loss_pct": 2.86,
      "profit_loss_amount": 20000,
      "cycle_number": 1,
      "traded_at": "2026-04-07T09:30:00"
    }
  ],
  "signals": [
    {
      "id": 1,
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "signal_type": "GOLDEN_CROSS | DEAD_CROSS | RSI_SIGNAL",
      "signal_value": {"ma5": 70500, "ma20": 68000},
      "confidence": 0.85,
      "action_taken": true,
      "detected_at": "2026-04-07T09:25:00"
    }
  ],
  "screening": {
    "total_screened": 20,
    "converted_count": 3,
    "conversion_rate": 15.0,
    "items": [
      {
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "screening_rank": 1,
        "volume": 5000000,
        "price_change_pct": 3.5,
        "converted_to_trade": true,
        "cycle_number": 1
      }
    ]
  },
  "errors": {
    "total_errors": 2,
    "items": [
      {
        "id": 1,
        "detail": {"msg": "timeout", "stock_code": "005930"},
        "recorded_at": "2026-04-07T10:30:00"
      }
    ]
  },
  "summary": {
    "report_date": "2026-04-07",
    "total_buy_count": 5,
    "total_sell_count": 3,
    "total_profit_loss": 45000,
    "win_rate": 0.67,
    "stop_loss_count": 1,
    "take_profit_count": 1,
    "strategy_sell_count": 1,
    "screening_count": 20,
    "screening_conversion_count": 3,
    "error_count": 2,
    "cycle_count": 10
  },
  "signal_accuracy": {
    "total_signals": 8,
    "acted_count": 5,
    "not_acted_count": 3,
    "confirmed_count": 4,
    "accuracy_rate": 80.0
  }
}
```

### weekly 커맨드

```bash
python scripts/query_analytics.py weekly 2026 15
```

```json
{
  "year": 2026,
  "week": 15,
  "trade_stats": {
    "year": 2026,
    "week": 15,
    "period": "2026-04-06 ~ 2026-04-12",
    "total_trades": 24,
    "daily_stats": [
      {
        "date": "2026-04-07",
        "buy_count": 5,
        "sell_count": 3,
        "total_profit_loss": 45000,
        "trades": 8
      }
    ]
  },
  "stock_frequency": [
    {
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "trade_count": 8,
      "buy_count": 4,
      "sell_count": 4,
      "total_pnl": 35000
    }
  ],
  "signal_performance": [
    {
      "signal_type": "GOLDEN_CROSS",
      "total": 12,
      "acted": 8,
      "act_rate": 66.7,
      "avg_confidence": 0.72
    }
  ],
  "risk_analysis": {
    "total_sells": 10,
    "by_reason": {
      "TAKE_PROFIT": {"count": 4, "avg_pnl_pct": 3.2, "total_pnl": 80000},
      "STOP_LOSS": {"count": 3, "avg_pnl_pct": -2.1, "total_pnl": -42000},
      "STRATEGY": {"count": 3, "avg_pnl_pct": 1.5, "total_pnl": 30000}
    }
  },
  "screening_conversion": {
    "period": "2026-04-06 ~ 2026-04-12",
    "total_screened": 60,
    "total_converted": 8,
    "overall_rate": 13.3,
    "daily": [
      {"date": "2026-04-07", "total_screened": 20, "converted": 3, "rate": 15.0}
    ]
  },
  "error_trend": {
    "period": "2026-04-06 ~ 2026-04-12",
    "total_errors": 5,
    "daily": [
      {"date": "2026-04-07", "error_count": 2}
    ]
  }
}
```

### range 커맨드

```bash
python scripts/query_analytics.py range 2026-03-01 2026-04-07
```

```json
{
  "period": "2026-03-01 ~ 2026-04-07",
  "cumulative_pnl": {
    "period": "2026-03-01 ~ 2026-04-07",
    "total_pnl": 250000,
    "trading_days": 18,
    "curve": [
      {"date": "2026-03-03", "daily_pnl": 15000, "cumulative_pnl": 15000},
      {"date": "2026-03-04", "daily_pnl": -5000, "cumulative_pnl": 10000}
    ]
  },
  "strategy_comparison": [
    {
      "signal_type": "GOLDEN_CROSS",
      "signal_count": 45,
      "acted_count": 30,
      "act_rate": 66.7,
      "avg_confidence": 0.68,
      "related_sells": 20,
      "total_pnl": 180000,
      "avg_pnl": 9000
    }
  ]
}
```

### risk 커맨드

```bash
python scripts/query_analytics.py risk --days 30
```

```json
{
  "lookback_days": 30,
  "total_sells": 25,
  "stop_loss": {
    "count": 8,
    "avg": -2.15,
    "min": -3.0,
    "max": -1.2,
    "median": -2.1
  },
  "take_profit": {
    "count": 10,
    "avg": 3.45,
    "min": 2.0,
    "max": 5.1,
    "median": 3.3
  },
  "strategy": {
    "count": 7,
    "avg": 1.2,
    "min": -0.5,
    "max": 4.0,
    "median": 1.1
  },
  "recommendation": {
    "stop_loss_rate": 0.0215,
    "take_profit_rate": 0.0345
  }
}
```

> **참고**: `stop_loss`·`take_profit`·`strategy`의 `avg`/`min`/`max`/`median` 단위는 **수익률 %** (예: -2.15 = -2.15%).
> `recommendation`의 `stop_loss_rate`·`take_profit_rate`는 **비율** (예: 0.0215 = 2.15%)로, `config.py`의 `MAX_LOSS_RATE`·`TAKE_PROFIT_RATIO` 형식과 동일합니다.

## 구현 이력 기록 규격

구현 이력은 **두 곳**에 기록한다:

### 1. DB (`implementation_logs` 테이블) — 영구 저장소
Claude Code가 구현 완료 시 `scripts/record_implementation.py`를 실행하여 기록:
- `title`: 변경 제목
- `category`: bug_fix / refactor / param_tuning / feature / enhancement / performance / docs / config
- `proposal_path`: 제안서 경로
- `changed_files`: 변경 파일 목록 (JSON: `{"src/파일.py": "변경 요약"}`)
- `verification`: 검증 결과 (JSON: `{"summary": "pytest ✅ | mypy ✅ | ruff ✅"}`)
- `background`: 배경 설명
- `expected_effect`: 기대 효과
- `implemented_at`: 구현 시각

### 2. `docs/CHANGELOG.md` — 최근 5건 rolling summary
- 가장 오래된 항목을 제거하고 새 항목을 맨 위에 추가
- Cowork 컨텍스트 로딩용 (전체 이력은 DB 조회)
- 기존 CHANGELOG 마크다운 형식 유지

## Claude Code 자동 구현 흐름

```
1. docs/BRIDGE_SPEC.md를 읽어 안전 게이트 규칙을 로드
2. docs/proposals/에서 상태가 ready인 파일을 날짜순으로 수집
3. 각 제안서에 대해:
   a. 안전 게이트 검증 (금지 영역, 파라미터 범위, 코드 변경 규칙)
   b. 위반 시 → skipped 처리, 위반 사유 기록, 다음 제안서로
   c. 통과 시 → 변경 스펙에 따라 코드 수정
   d. pytest + mypy + ruff 실행
   e. 전부 pass → implemented 처리, DB implementation_logs 기록 + CHANGELOG rolling 갱신
   f. 하나라도 fail → git restore로 원복, failed 처리, 실패 사유 기록
3. implemented된 제안서가 1개 이상이면:
   a. launchctl stop com.kis.autotrader
   b. 5초 대기
   c. launchctl start com.kis.autotrader
   d. 10초 후 프로세스 상태 확인 (launchctl list | grep com.kis.autotrader)
4. 결과 요약 출력
```
