# [Plan] Watchdog 개선 — 스케줄러 작동 감지

## 메타데이터
- 작성일: 2026-04-06
- 우선순위: high
- 의존성: 없음
- 관련 파일: `scripts/watchdog.sh`, `src/api/health.py`

## 배경 및 문제

2026-04-06(월) 장중에 스케줄러 작업(08:30 장 시작 전, 08:55 장중 매매 등록)이 실행되지 않았으나,
watchdog가 이를 감지하지 못해 12:28 수동 재시작까지 약 3.5시간 동안 매매가 중단되었다.

### 근본 원인
현재 watchdog는 **로그 파일 수정 시각**만으로 hang을 판단한다.
Telegram Bot이 30초마다 long-polling하며 로그를 갱신하기 때문에,
스케줄러가 멈춰도 로그는 항상 "fresh" 상태로 유지되어 hang 감지가 불가능하다.

### 영향
- 장중 매매 완전 중단 (시그널 미생성, 체결 0건)
- 수동 확인 전까지 인지 불가
- 모의투자 환경이라 실제 손실은 없었으나, 실전에서는 치명적

## 목표

장중 시간에 스케줄러 작업이 실제로 실행되고 있는지 확인하여,
비정상 상태 감지 시 자동 재시작 및 Telegram 알림을 보낸다.

## 개선 방안

### 방안 1: 헬스체크 API 기반 감지 (권장)

현재 헬스체크 응답에 `cycle_count`와 `daily_api_calls`가 포함되어 있다:
```json
{
  "status": "ok",
  "components": {
    "trading": {
      "cycle_count": 0,
      "daily_api_calls": 0
    }
  }
}
```

**watchdog 로직 변경**:
1. 장중 시간(09:05~15:20)에 `curl http://localhost:8080/health` 호출
2. `cycle_count == 0`이면 **스케줄러 미작동** 판단
3. 이전 체크와 비교하여 `cycle_count`가 변하지 않으면 **hang** 판단
4. 감지 시 → 재시작 + Telegram 알림

**장점**: 기존 인프라(헬스체크 API) 활용, 정확한 매매 활동 기반 판단
**구현 규모**: watchdog.sh 수정만으로 충분

### 방안 2: 헬스체크 API 확장

`/health` 응답에 추가 필드를 포함:
- `last_trading_cycle_at`: 마지막 매매 사이클 실행 시각
- `scheduler_jobs_status`: 등록된 스케줄러 작업 상태

이 방안은 방안 1로 부족할 경우에만 추가 적용.

## 변경 범위

### 수정 파일
| 파일 | 변경 내용 |
|------|----------|
| `scripts/watchdog.sh` | 헬스체크 API 기반 감지 로직 추가 |

### 선택적 수정 (방안 2 적용 시)
| 파일 | 변경 내용 |
|------|----------|
| `src/api/health.py` | `last_trading_cycle_at` 필드 추가 |
| `src/engine.py` | 마지막 사이클 시각 기록 |

## 검증 기준

- [ ] 장중 시간에 `cycle_count == 0`이면 5분 이내 감지
- [ ] 감지 시 자동 재시작 실행
- [ ] 재시작 후 Telegram 알림 전송
- [ ] 장외 시간에는 오탐 없음 (기존 동작 유지)
- [ ] 헬스체크 API 장애 시에도 기존 로그 기반 감지 fallback 동작

## 구현 순서

1. watchdog.sh에 헬스체크 기반 감지 로직 추가
2. 기존 로그 기반 감지를 fallback으로 유지
3. 수동 테스트로 검증
