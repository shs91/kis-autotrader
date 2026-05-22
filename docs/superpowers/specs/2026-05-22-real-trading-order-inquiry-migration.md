# 실전 전환 시 KIS 조회 API 기반 주문 체결/잔류 정리 — 설계 노트 (연기)

- 작성일: 2026-05-22
- 상태: **DEFERRED (실전 전환 준비 시 구현)** — 자동 구현 파이프라인 대상 아님
- 관련: PR #33(체결 확인 잔고 기반), PR #34(미체결 추적·정리), 메모리 `project_kis_mock_api_limits`

## 배경

모의투자(`KIS_ENV=virtual`)에서 KIS 조회 API가 미지원이라 현재 구현은 우회 방식이다:
- **체결 확인**: `inquire-daily-ccld`가 모의에서 당일 자료를 안 줘서 → **잔고 변동(get_balance)** 으로 판정, 체결가는 현재가로 근사.
- **미체결 정리**: `inquire-psbl-rvsecncl`가 모의에서 "없는 서비스 코드" → **인메모리 세션 추적**(`_pending_orders`)만. 재시작 전 잔류는 못 잡음.

실전(`KIS_ENV=real`)에선 이 조회 API들이 작동하므로 더 정확/견고하게 갈 수 있다.

## 목표 (실전)

1. **정확한 체결가/수량 기록** — 체결조회로 실제 체결 단가·수량 확보(현재가 근사 제거).
2. **재시작을 넘는 잔류 미체결 정리** — KIS에 남은 미체결 주문을 열거→오래된 것 취소. (실전 미체결 = 실제 자금 노출이므로 핵심 가치)

## 설계 — env 분기 + 폴백 (검증된 모의 경로 불변)

추상화 seam을 도입하되, **모의 동작은 잔고 기반 그대로 유지**하고 실전에서만 조회 API 경로를 활성화한다. 실전 경로도 **실패 시 잔고 기반으로 폴백**(방어적 — 조회 API는 강화이고 잔고 기반이 안전망).

### (a) 체결 확인 — `_confirm_fill` 분기
- `real`: 주문 후 체결조회(`inquire-daily-ccld`, TR `TTTC8001R`)로 `order_no` 일치 체결분 폴링 → 실제 `AVG_PRVS`(체결가)·`TOT_CCLD_QTY`(수량) 사용. 미조회 시 잔고 변동으로 폴백.
- `virtual`: 현행 잔고 변동 그대로.
- 적용점: `_execute_buy`/`_execute_sell`의 `_confirm_fill` 호출부. 체결가를 `int(price)` 근사 대신 조회값으로.

### (b) 잔류 정리 — KIS 미체결 열거
- 신규 `AccountAPI.get_open_orders()` — `inquire-psbl-rvsecncl`(정정취소가능주문조회, real TR id 확정 필요: `TTTC0084R` 계열 — 실전 문서로 검증) 호출, 미체결(잔량>0) 주문 목록 반환.
- `pre_market` + 주기적으로: `real`이면 KIS 미체결을 열거 → `_pending_orders`에 동기화(재시작 전 잔류 포함) → 타임아웃 초과분 `order.cancel`. 이로써 **크로스-리스타트 잔류 정리**가 가능.
- `virtual`: 현행 인메모리만.

### 공통
- 모든 실전 경로는 `if settings.kis.env == "real":` 게이트로 격리. 모의 회귀 0.
- `order.cancel`는 모의/실전 공용(이미 존재) — 단 모의 cancel 실제 동작도 cutover 전 미검증이므로 체크리스트에 포함.

## 리스크 & 실전 Cutover 검증 체크리스트

이 경로들은 **모의에서 실 API 계약 검증 불가** → 실전에서 처음 실행되는 주문 경로다. 로직은 mock 응답으로 단위테스트하되, 실 API 대조는 cutover 시 필수:

- [ ] `inquire-daily-ccld`(real) 응답 필드(`ODNO`/`AVG_PRVS`/`TOT_CCLD_QTY`) 실제 스키마 확인 — 소액 1주 매수 후 조회로 대조.
- [ ] `inquire-psbl-rvsecncl`(real) TR id·path·응답 필드 확정 — 미체결 1건 만들어 열거 확인.
- [ ] `order.cancel`(real) 실제 취소 동작 확인 — 미체결 주문 취소 후 잔고/미체결 반영 확인.
- [ ] 체결가 기록이 HTS 체결 단가와 일치하는지 1건 대조.
- [ ] 폴백 경로(조회 실패 → 잔고 기반) 동작 확인.
- [ ] 소액·단일 종목으로 1일 관찰 후 정상 시 일반 운영 전환.

## 비목표
- 모의 동작 변경 없음. 실전 전환 전까지 현행(잔고 기반 + 인메모리 추적) 유지.
- 자동 구현 파이프라인(`docs/proposals/ ready`) 대상 아님 — 실 API 검증이 필요한 수동 작업.
