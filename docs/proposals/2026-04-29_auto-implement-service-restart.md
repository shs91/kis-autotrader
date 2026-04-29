# auto-implement 후 서비스 재시작 누락 수정

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-29
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: scripts/run_auto_implement.sh

## 현상 분석

2026-04-28 `screening-to-engine-pipeline-fix` 제안서가 `implemented` 처리되었으나,
실행 중인 autotrader 프로세스가 재시작되지 않아 **수정 코드가 반영되지 않은 상태로 계속 가동** 중이다.

### 근거 데이터
- 실행 중 프로세스 시작 시각: `2026-04-27 17:16:39 KST` (로그 확인)
- 04-28 수정 커밋 시각: `2026-04-28 17:22:32 KST`
- 04-29 EVAL_TARGETS: 1,984건 **전수** `screening: 0` (쿼리 9, EVAL_TARGETS 상세)
- `get_by_date(date.today())` 직접 실행 시 5,970건 반환 확인 → 코드 문제 아닌 **배포 문제**

### 원인
`scripts/run_auto_implement.sh`에 서비스 재시작 로직이 없다.
BRIDGE_SPEC에 "implemented된 제안서가 1개 이상이면 launchctl stop/start" 명시되어 있으나,
실제 쉘 스크립트에는 Claude Code 실행과 패치노트 등록만 포함되어 있다.

## 제안 내용

`scripts/run_auto_implement.sh`에 구현 성공 시 서비스 재시작 로직을 추가한다.
Claude Code 출력에서 `implemented` 키워드를 감지하여 조건부로 재시작한다.

## 변경 스펙

### 파일별 변경사항

- `scripts/run_auto_implement.sh`:
  - Claude Code 실행 후, 로그 파일에서 `implemented` 문자열을 검색
  - 발견 시 `launchctl stop com.kis.autotrader` → 5초 대기 → `launchctl start com.kis.autotrader` 실행
  - 10초 후 프로세스 상태 확인 (`launchctl list | grep com.kis.autotrader`)
  - 재시작 결과를 로그에 기록

변경 전 (라인 27 이후):
```bash
echo "=== Auto-implement finished at $(date) ===" >> "$LOG_FILE"
```

변경 후:
```bash
echo "=== Auto-implement finished at $(date) ===" >> "$LOG_FILE"

# 구현 성공 시 서비스 재시작 (BRIDGE_SPEC 규격)
if grep -q "implemented" "$LOG_FILE" 2>/dev/null; then
  echo "=== Service restart started at $(date) ===" >> "$LOG_FILE"
  launchctl stop com.kis.autotrader 2>> "$LOG_FILE" || true
  sleep 5
  launchctl start com.kis.autotrader 2>> "$LOG_FILE" || true
  sleep 10
  if launchctl list 2>/dev/null | grep -q "com.kis.autotrader"; then
    echo "서비스 재시작 완료" >> "$LOG_FILE"
  else
    echo "서비스 재시작 실패 — 수동 확인 필요" >> "$LOG_FILE"
  fi
  echo "=== Service restart finished at $(date) ===" >> "$LOG_FILE"
else
  echo "구현된 제안서 없음 — 재시작 스킵" >> "$LOG_FILE"
fi
```

## 기대 효과

- auto-implement 파이프라인에서 구현된 코드가 **즉시 반영**됨
- 04-28 파이프라인 수정이 실제 적용되어 스크리닝→시그널 전환율 개선 기대
- 향후 모든 코드 변경이 다음 거래일부터 바로 효과를 발휘

## 롤백

`scripts/run_auto_implement.sh`에서 추가된 재시작 블록을 제거한다.
서비스 재시작은 별도 영향 없으므로 롤백 시에도 수동 재시작만 필요.
