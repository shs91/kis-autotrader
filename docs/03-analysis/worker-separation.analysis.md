# [Check] worker-separation Gap Analysis

> **Date**: 2026-04-15
> **Match Rate**: 88%
> **Status**: Gap 해소 필요 (90% 미만)

## Match Rate 산출

| 카테고리 | 전체 | Match | Gap | Extra | Changed |
|----------|:----:|:-----:|:---:|:-----:|:-------:|
| Data Model | 12 | 12 | 0 | 0 | 0 |
| Queue API | 6 | 5 | 1 | 1 | 0 |
| Handlers | 8 | 7 | 0 | 1 | 0 |
| Runner | 4 | 4 | 0 | 0 | 0 |
| Screener | 3 | 3 | 0 | 1 | 1 |
| Rate Limiter | 5 | 5 | 0 | 0 | 1 |
| Engine enqueue | 8 | 6 | 0 | 0 | 2 |
| Scheduler quota | 3 | 3 | 0 | 0 | 0 |
| Config | 2 | 2 | 0 | 1 | 0 |
| main.py | 3 | 3 | 0 | 1 | 0 |
| Infra | 3 | 2 | 1 | 0 | 0 |
| Exceptions | 2 | 0 | 2 | 0 | 0 |
| **합계** | **59** | **52** | **4** | **4** | **4** |

**Match Rate: 88% (52/59)**

## 주요 Gap (해소 시 90%+ 달성)

1. **_execute_buy/_sell Telegram 직접 호출 잔재** — Design은 enqueue 전환을 명시했으나 매수/매도 실시간 알림이 아직 직접 호출
2. **WorkerError, TaskExecutionError 예외 미정의** — 컨벤션 상 커스텀 예외 필요
3. **Dead Letter Telegram 알림 미구현** — DEAD 태스크 발생 시 알림 없음

## 경미한 Gap (차후 개선)

4. **배치 INSERT 미구현** — 개별 처리 중이나 기능상 문제 없음
5. **ix_task_queue_completed 인덱스 누락** — cleanup 성능 최적화용

## Extra (Design에 없지만 추가된 개선)

- DailyPerformanceHandler 추가
- enqueue 반환 None (중복 스킵)
- WorkerConfig.enabled 토글
- Graceful shutdown 처리
- ScreeningWorker interval 파라미터화
