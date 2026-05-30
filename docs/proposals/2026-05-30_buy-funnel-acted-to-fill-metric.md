# acted→실체결 매핑률 관측 — BUY_OUTCOME 퍼널 메트릭 도입

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-30
- 상태: implemented
- 우선순위: high
- 카테고리: performance
- 관련파일: src/engine.py, tests/test_engine_buy_funnel.py

## 현상 분석

5월 월간 리포트 §신규 미해결 항목 2 / §근본 원인 분석에서 **acted vs 실 체결 괴리**가
"6월의 핵심 과제"로 지목되었다.

- 5월 ENSEMBLE **acted 5,332건 / 실 체결 29건 = 0.54% 매핑률**.
- W22 시그널 act_rate 86.6%(5/25)·37.4%(5/27)·43.7%(5/28)에도 실 체결은 0~1건.

원인은 구조적이다. 엔진은 매수 게이트(일일한도·종목별한도·`check_buy_gates`·포지션사이즈)를
모두 통과하면 **`action_taken=True`를 먼저 기록한 뒤**(현재 src/engine.py:850-853) `_execute_buy`를 호출한다.
그런데 `_execute_buy`는 그 **이후에** 여러 종단 지점에서 다시 매수를 중단할 수 있다:

| `_execute_buy` 종단 지점 (현재 위치) | 메트릭 기록 여부 |
|--------------------------------------|------------------|
| 당일 매매불가 블랙리스트 스킵 (src/engine.py:1039) | **없음** (debug 로그만) |
| 종목마스터 시장조치 차단 (src/engine.py:1046-1052) | **없음** (warning 로그만) |
| 치명 공시 차단 (src/engine.py:1056-1066) | `BUY_DISCLOSURE_BLOCK` |
| 미체결 주문 중복 억제 (src/engine.py:1069) | **없음** |
| 매매불가 주문 거부 (src/engine.py:1082-1093) | `BUY_UNTRADABLE` |
| 주문 실패/예외 (src/engine.py:1094-1098) | **없음** (logger.exception만) |
| 체결 미확인 (src/engine.py:1110-1126) | `ORDER_UNFILLED`(side=BUY) |
| 체결 성공 (src/engine.py:1128~1169) | **없음** (trades 테이블만) |

즉 `action_taken=true`로 집계되는 5,332건의 상당수는 게이트를 통과했으나 `_execute_buy`
내부에서 차단(특히 공시·시장조치)된 케이스다. 5/28 230980에 대한 conf 1.000 신호가 매 사이클
acted=True로 찍혔지만 공시 게이트가 전량 차단한 것이 대표적. **종단별 분포가 일관되게 기록되지 않아
"acted가 어디서 새는지"를 단일 쿼리로 볼 수 없다.**

> 참고: 5/30 v0.7.0이 정리매매·치명 공시 종목을 스크리닝 단계에서 사전 배제해 이 누수의 큰 줄기를
> 줄였다. 본 제안서는 그 효과를 **정량 확인**하고 남은 누수(시장조치/미체결/중복억제)를 계량한다.

본 제안서는 **action_taken 컬럼 의미 자체는 건드리지 않는다**(그 변경은 DB 스키마가 얽혀 별도 검토 사안).
대신 `_execute_buy`의 모든 종단에 **통일된 퍼널 메트릭**을 1건씩 적재해 acted→체결 깔때기를 가시화한다.

## 제안 내용

`_execute_buy`의 모든 종단 분기에 `BUY_OUTCOME` 시스템 메트릭을 `outcome` 코드와 함께 1건 기록한다.

- `action_taken=True`는 `_execute_buy` 호출 직전(src/engine.py:850-853)에서만 설정되고,
  모든 매수 경로는 정확히 하나의 `_execute_buy` 종단을 통과한다.
  따라서 **`BUY_OUTCOME` 총합 = 매수 acted 건수**, **`outcome=FILLED` = 실 체결 건수**가 되어
  `acted→체결 매핑률 = FILLED / 총합`을 단일 쿼리로 산출할 수 있다.
- 기존 `BUY_DISCLOSURE_BLOCK`·`BUY_UNTRADABLE` 메트릭은 하위호환을 위해 유지하고,
  `BUY_OUTCOME`는 그와 **병행** 적재(중복 카운트가 아니라 별도 metric_type).
- 매수/매도/게이트 동작은 변경하지 않는다(순수 관측). 기록 실패는 swallow.

## 변경 스펙

### 파일별 변경사항

- `src/engine.py` `_execute_buy`(src/engine.py:1033)의 각 종단 분기에서 `return` 직전에
  `self._record_metric("BUY_OUTCOME", {"stock_code": stock_code, "outcome": <코드>, "cycle": self._cycle_count})`
  를 1줄 추가한다. 종단별 `outcome` 코드:

  | 종단 (현재 위치) | outcome 코드 |
  |------------------|--------------|
  | 당일 매매불가 블랙리스트 스킵 (src/engine.py:1039) | `SKIP_UNTRADABLE_TODAY` |
  | 종목마스터 시장조치 차단 (src/engine.py:1052) | `BLOCK_MARKET_ACTION` |
  | 치명 공시 차단 (src/engine.py:1066, 기존 `BUY_DISCLOSURE_BLOCK`와 병행) | `BLOCK_DISCLOSURE` |
  | 미체결 주문 중복 억제 (src/engine.py:1069 `return`) | `SUPPRESS_PENDING` |
  | 매매불가 주문 거부 (src/engine.py:1093, 기존 `BUY_UNTRADABLE`와 병행) | `ORDER_UNTRADABLE` |
  | 주문 실패/예외 (src/engine.py:1095·1098 `return`) | `ORDER_FAIL` |
  | 체결 미확인 (src/engine.py:1126, 기존 `ORDER_UNFILLED`와 병행) | `UNFILLED` |
  | 체결 성공 (src/engine.py:1148 `_record_trade_to_db` 직후) | `FILLED` |

  > 중복 코드 방지를 위해 한 줄짜리 내부 헬퍼 `self._record_buy_outcome(stock_code, outcome)`를
  > 추가하고 각 종단에서 호출해도 좋다(구현 재량). 시그니처 변경이 아니라 신규 메서드이므로
  > 기존 테스트에 영향 없음.

### 추가 테스트

- `tests/test_engine_buy_funnel.py` 신설. 기존 `tests/test_engine_untradable_blacklist.py`·
  `tests/test_engine_disclosure_risk_gate.py`의 `_execute_buy` 테스트 패턴(주문 API·체결확인 모킹)을 따른다.
  `_record_metric`을 감시해 종단별 `outcome`을 검증:
  1. 정상 체결 경로 → `BUY_OUTCOME outcome=FILLED` 1건.
  2. 당일 매매불가 블랙리스트 종목 → `outcome=SKIP_UNTRADABLE_TODAY`.
  3. 치명 공시 차단 종목 → `outcome=BLOCK_DISCLOSURE` (+ 기존 `BUY_DISCLOSURE_BLOCK`도 유지됨).
  4. 매매불가 주문 거부 → `outcome=ORDER_UNTRADABLE` (+ 기존 `BUY_UNTRADABLE` 유지).
  5. 체결 미확인 → `outcome=UNFILLED`.
  6. 한 번의 `_execute_buy` 호출은 정확히 1건의 `BUY_OUTCOME`만 남김(종단 상호배타 검증).

## 기대 효과

- **깔때기 단일 쿼리화**: `SELECT detail->>'outcome', COUNT(*) FROM system_metrics WHERE metric_type='BUY_OUTCOME'
  GROUP BY 1` 한 방으로 "acted 5,332 → 어디서 몇 건 샜는지"를 일·주 단위로 분해.
  매핑률 0.54%의 구성(공시/시장조치/미체결/중복억제/실패)을 정량 확인.
- **v0.7.0 효과 검증**: 스크리닝 사전 배제 도입 전후 `BLOCK_DISCLOSURE`/`BLOCK_MARKET_ACTION` 비중
  감소를 직접 측정 → "게이트 호출 644→0" 주장을 acted 관점에서 재확인.
- **운영 가시성**: 헬스체크·일일 리포트가 종단 분포를 인용해 "왜 신호는 많은데 체결이 없나"를 즉답.
- **무위험·저비용**: 매매 경로 불변, `system_metrics` 기존 테이블·`_record_metric` 기존 큐 재사용.
  DB 마이그레이션·신규 의존성·신규 env 없음. 변경 파일 2개.

## 롤백

- `git restore src/engine.py` + `tests/test_engine_buy_funnel.py` 삭제로 완전 원복.
- 관측 전용이므로 잔존 시에도 매매 동작에 영향 없음(메트릭 적재만 발생).
