# Runbook: TIMESTAMPTZ 손상 데이터 백필 (2026-05-12)

## 컨텍스트

관련 제안서: `docs/proposals/2026-05-12_timestamp-naive-to-aware-utc.md`

위 제안이 implemented 되면 **신규** row의 timestamp는 정상 저장된다. 본 runbook은 그 전에 박혀버린 **기존** row를 보정하는 수동 절차다.

`alembic/versions/` 신규 마이그레이션 생성은 BRIDGE_SPEC 금지 영역이므로 자동 파이프라인 대상 아님 — 본 절차는 **수동 PDCA로만 진행**한다.

## 손상 유형 (실측 기반)

| 테이블.컬럼 | 손상 패턴 | 입력 코드 |
|------------|----------|-----------|
| `trades.traded_at` | KST 값이 UTC로 박힘 → 절대 시각 +9시간 어긋남 | `engine.py:969` (KST naive) |
| `screening_results.screened_at` | **+18시간 정황** (worker 별도 가설) | `worker/screener.py:204` |
| `signals.detected_at` | 미확인 — 진단 필요 | (호출자 확인 필요) |
| `system_metrics.recorded_at` | 손상 없음 (utcnow naive를 UTC로 해석 = 정상) | `repository.py:884` |
| `*.created_at`, `*.updated_at` | 손상 없음 (default=utcnow) | 컬럼 default |

## 사전 준비 (반드시 순서대로)

```bash
# 1. 매매 엔진 중단 (백필 중 신규 INSERT 차단)
launchctl stop com.kis.autotrader

# 2. 자동 구현 일시 중단 (백필 작업 중 코드 변경 트리거 차단)
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.kis.autoimplement.plist

# 3. DB 백업
cd ~/IdeaProjects/kis-autotrader
bash scripts/backup_db.sh

# 4. 백업 파일 확인 (백필 실패 시 복원에 사용)
ls -lh backups/ | tail -3
```

## 1단계: 진단 쿼리 (백필 전 반드시 실행)

손상 카운트와 분포를 먼저 확인해 가설을 검증한 뒤에 UPDATE 한다.

```sql
-- trades: KST 변환 결과의 시각 분포
SELECT
  to_char(traded_at AT TIME ZONE 'Asia/Seoul', 'HH24') AS kst_hour,
  COUNT(*) AS n,
  MIN(traded_at) AS first_at,
  MAX(traded_at) AS last_at
FROM trades
GROUP BY 1
ORDER BY 1;
-- 예상: 모든 row가 KST 18~24시대에 분포 (정상이면 09~15시여야 함)
-- 만약 분포가 18~24시에 몰려 있으면 +9 시간 어긋남 확정

-- screening_results: 시각 분포 (가설: +18시간 어긋남)
SELECT
  to_char(screened_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24') AS kst_hour,
  COUNT(*) AS n
FROM screening_results
WHERE screened_at >= now() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 30;
-- 정상: KST 09:00~15:30 분포
-- +9 어긋남: KST 18:00~24:30 분포
-- +18 어긋남: KST 다음날 03:00~09:30 분포 (즉 자정 넘어감)

-- signals: 진단
SELECT
  to_char(detected_at AT TIME ZONE 'Asia/Seoul', 'HH24') AS kst_hour,
  COUNT(*) AS n
FROM signals
GROUP BY 1
ORDER BY 1;

-- 손상 시작일 추정 (코드 도입 시점 파악용)
SELECT MIN(traded_at), MAX(traded_at), COUNT(*) FROM trades;
SELECT MIN(screened_at), MAX(screened_at), COUNT(*) FROM screening_results;
SELECT MIN(detected_at), MAX(detected_at), COUNT(*) FROM signals;
```

**판정 기준**:
- KST 18~24 분포 → 9시간 빼면 보정 완료 (`INTERVAL '9 hours'`)
- KST 다음날 03~09 분포 → 18시간 빼야 함 (`INTERVAL '18 hours'`)
- 분포가 섞여 있으면 → 시기별로 다른 패턴. 코드 변경 시점으로 row를 분할해 처리 (`WHERE traded_at < '특정일'`)

## 2단계: trades 백필

가장 단순한 케이스. 분포가 KST 18~24시대로 일관되면 일괄 -9시간.

```sql
-- 백필 전 sample 확인
SELECT id, traded_at AT TIME ZONE 'Asia/Seoul' AS before_kst
FROM trades ORDER BY id DESC LIMIT 5;

-- 백필 실행 (트랜잭션으로 보호)
BEGIN;
UPDATE trades
SET traded_at = traded_at - INTERVAL '9 hours'
WHERE traded_at < '<implemented_시점>';  -- 제안서 implemented 시각 ISO 8601로 치환

-- 검증: 매매시간 범위(KST 09:00~15:30)에 들어왔는지
SELECT
  COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM traded_at AT TIME ZONE 'Asia/Seoul') BETWEEN 9 AND 15) AS in_range,
  COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM traded_at AT TIME ZONE 'Asia/Seoul') NOT BETWEEN 9 AND 15) AS out_of_range
FROM trades
WHERE traded_at < '<implemented_시점>';

-- in_range가 전체와 동일하고 out_of_range = 0 이면 COMMIT, 아니면 ROLLBACK
COMMIT;  -- 또는 ROLLBACK
```

## 3단계: screening_results 백필 (가설 확인 필수)

worker 손상 패턴은 단순 +9가 아닐 수 있음. **반드시 1단계 진단으로 패턴을 확정한 뒤 INTERVAL을 결정**한다.

```sql
-- 가설 A: +9시간 어긋남
BEGIN;
UPDATE screening_results
SET screened_at = screened_at - INTERVAL '9 hours'
WHERE screened_at < '<implemented_시점>';
-- 검증 후 COMMIT/ROLLBACK

-- 가설 B: +18시간 어긋남
BEGIN;
UPDATE screening_results
SET screened_at = screened_at - INTERVAL '18 hours'
WHERE screened_at < '<implemented_시점>';
-- 검증 후 COMMIT/ROLLBACK
```

**진단 미해결 시**: worker 컨테이너 TZ, screener.py 호출자 코드를 추가 조사해 패턴 확정 후 진행.

## 4단계: signals 백필 (해당 시)

1단계 진단으로 손상 확인되면:

```sql
BEGIN;
UPDATE signals
SET detected_at = detected_at - INTERVAL '9 hours'
WHERE detected_at < '<implemented_시점>';
COMMIT;  -- 검증 후
```

## 5단계: 전체 검증

```sql
-- 분포 확인: 모두 매매시간 안에 들어왔는지
SELECT 'trades' AS tbl,
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM traded_at AT TIME ZONE 'Asia/Seoul') BETWEEN 9 AND 15) AS ok,
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM traded_at AT TIME ZONE 'Asia/Seoul') NOT BETWEEN 9 AND 15) AS ng
FROM trades
UNION ALL
SELECT 'screening_results',
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM screened_at AT TIME ZONE 'Asia/Seoul') BETWEEN 9 AND 15),
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM screened_at AT TIME ZONE 'Asia/Seoul') NOT BETWEEN 9 AND 15)
FROM screening_results
UNION ALL
SELECT 'signals',
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM detected_at AT TIME ZONE 'Asia/Seoul') BETWEEN 9 AND 15),
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM detected_at AT TIME ZONE 'Asia/Seoul') NOT BETWEEN 9 AND 15)
FROM signals;
```

전부 `ng = 0`이어야 한다.

```bash
# 분석 쿼리로 daily 리포트 재생성 후 비교
.venv/bin/python scripts/query_analytics.py daily 2026-05-12 | jq '.trades[] | .traded_at'
# 시각이 KST 09~15시대로 나오는지 확인
```

## 6단계: 재가동

```bash
# 매매 엔진 재시작
launchctl start com.kis.autotrader

# 자동 구현 재활성화
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kis.autoimplement.plist

# 로그 확인
tail -f logs/autotrader.log
```

## 롤백 절차

UPDATE 결과가 잘못된 경우:

```bash
# 방법 1: 트랜잭션 중이면 ROLLBACK
# 방법 2: 백업 파일 복원
docker-compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB < backups/<백업파일>.sql
```

또는 역방향 UPDATE:

```sql
-- -9 시간 적용을 잘못한 경우 되돌리기
UPDATE trades
SET traded_at = traded_at + INTERVAL '9 hours'
WHERE traded_at < '<implemented_시점>';
```

## 작업 후 확인 사항

- [ ] 진단 쿼리로 손상 패턴 확정
- [ ] 매매 엔진·자동 구현 중단 확인
- [ ] DB 백업 완료 확인
- [ ] trades 백필 + 검증
- [ ] screening_results 백필 + 검증 (가설 확인 후)
- [ ] signals 백필 + 검증 (해당 시)
- [ ] daily 리포트 재생성 비교
- [ ] 매매 엔진·자동 구현 재기동
- [ ] 다음 daily 분석가 보고에서 "timestamp anomaly" 항목 사라졌는지 확인

## 자동 파이프라인 영향

- 본 runbook은 alembic 마이그레이션 없이 직접 SQL UPDATE — BRIDGE_SPEC의 alembic 금지 영역에 저촉 안 됨
- 그러나 데이터 직접 수정이므로 자동 게이트로 처리 불가, **수동 진행 필수**
- 작업 후 implementation_logs에 수동으로 기록 권장:
  ```bash
  .venv/bin/python scripts/record_implementation.py \
    --title "TIMESTAMPTZ 손상 데이터 백필" \
    --category bug_fix \
    --proposal "docs/runbooks/2026-05-12_timestamp-utc-backfill.md" \
    --files '{"db:trades": "UPDATE -9h", "db:screening_results": "UPDATE -Nh", "db:signals": "UPDATE -9h"}' \
    --verification "분포 검증 + daily 리포트 비교 완료" \
    --background "코드 수정 후 손상 row 보정"
  ```
