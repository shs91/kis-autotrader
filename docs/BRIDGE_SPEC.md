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

| 파라미터 | 현재값 | 자동 변경 허용 범위 |
|----------|--------|---------------------|
| MAX_LOSS_RATE | 0.03 (3%) | 0.01 ~ 0.05 |
| MAX_POSITION_RATIO | 0.2 (20%) | 0.05 ~ 0.3 |
| DAILY_TRADE_LIMIT | 10 | 5 ~ 20 |
| TAKE_PROFIT_RATIO | 0.05 (5%) | 0.02 ~ 0.10 |
| MA short_period | 5 | 3 ~ 10 |
| MA long_period | 20 | 15 ~ 60 |
| RSI period | 14 | 7 ~ 21 |
| RSI oversold | 30 | 20 ~ 40 |
| RSI overbought | 70 | 60 ~ 80 |
| 스케줄러 interval 하한 | 10.0 | 10.0 ~ 60.0 |
| SCREENING_TOP_N | 20 | 5 ~ 50 |
| SCREENING_INTERVAL_CYCLES | 30 | 10 ~ 100 |
| BALANCE_CACHE_TTL | 30.0 | 10.0 ~ 120.0 |

범위를 벗어나는 변경이 제안서에 있으면 해당 제안서는 `skipped` 처리.

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

## CHANGELOG 규격

Claude Code가 자동으로 기록:

```markdown
## [YYYY-MM-DD HH:MM] 제안 제목
- 제안서: docs/proposals/YYYY-MM-DD_제목.md
- 카테고리: param_tuning
- 변경 파일:
  - src/파일.py: 변경 요약
- 검증 결과: pytest ✅ | mypy ✅ | ruff ✅
- 프로세스 재시작: ✅
```

## Claude Code 자동 구현 흐름

```
1. docs/BRIDGE_SPEC.md를 읽어 안전 게이트 규칙을 로드
2. docs/proposals/에서 상태가 ready인 파일을 날짜순으로 수집
3. 각 제안서에 대해:
   a. 안전 게이트 검증 (금지 영역, 파라미터 범위, 코드 변경 규칙)
   b. 위반 시 → skipped 처리, 위반 사유 기록, 다음 제안서로
   c. 통과 시 → 변경 스펙에 따라 코드 수정
   d. pytest + mypy + ruff 실행
   e. 전부 pass → implemented 처리, CHANGELOG 기록
   f. 하나라도 fail → git restore로 원복, failed 처리, 실패 사유 기록
3. implemented된 제안서가 1개 이상이면:
   a. launchctl stop com.kis.autotrader
   b. 5초 대기
   c. launchctl start com.kis.autotrader
   d. 10초 후 프로세스 상태 확인 (launchctl list | grep com.kis.autotrader)
4. 결과 요약 출력
```
