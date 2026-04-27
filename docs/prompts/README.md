# 분석 프롬프트 구조 가이드

## 개요

분석 작업을 **Code (자동 실행)** 과 **Cowork (대화형 판단)** 으로 분리한다.

- **Code**: 결정론적 작업 (쿼리 실행, 정형 리포트 생성, 임계값 기반 제안서)
- **Cowork**: 해석적 작업 (효과 검증, 전략 방향 논의, 아키텍처 판단)

## 파일 구조

```
docs/prompts/
├── README.md                 ← 이 파일
├── _common_rules.md          ← 공통 규칙 (타임존, enum, 수익률/승률 정의, 임계값)
├── daily_routine.md          ← [Code] 일간 자동 분석 (launchd, 평일 16:30)
├── weekly_routine.md         ← [Code] 주간 자동 통계 (launchd, 금 18:00)
├── weekly_review.md          ← [Cowork] 주간 해석·판단 (토요일, 수동)
├── monthly_review.md         ← [Cowork] 월간 전략 논의 (마지막 금/주말, 수동)
├── daily_analysis.md         ← [레거시] 기존 통합 프롬프트 (참조용 보존)
├── weekly_analysis.md        ← [레거시] 기존 통합 프롬프트 (참조용 보존)
└── monthly_analysis.md       ← [레거시] 기존 통합 프롬프트 (참조용 보존)
```

## 실행 흐름

### 평일 (완전 자동)

```
16:30  run_daily_analysis.sh → claude -p daily_routine.md
         ├─ 쿼리 1~12 실행
         ├─ docs/reports/YYYY-MM-DD_daily.md 생성
         └─ 임계값 위반 시 docs/proposals/YYYY-MM-DD_*.md 생성

17:15  run_auto_implement.sh → claude -p auto_implement_prompt.txt
         ├─ docs/proposals/ 에서 ready 제안서 수집
         ├─ 안전 게이트 검증 → 구현 → pytest/mypy/ruff
         └─ implemented 처리 + DB 기록 + 서비스 재시작
```

### 금요일 (자동 + 수동)

```
16:30  일간 루틴 (위와 동일)
17:15  일간 구현 (위와 동일)
18:00  run_weekly_analysis.sh → claude -p weekly_routine.md
         ├─ 주간 통계 집계
         ├─ docs/reports/YYYY-Www_weekly.md 생성 (통계 섹션만)
         └─ "중기 아키텍처 논의" 섹션은 데이터만 채우고 판단 비워둠

토/일  [Cowork] weekly_review.md (사용자 시간 될 때)
         ├─ 주간 리포트의 빈 섹션 채우기
         ├─ 이전 제안서 효과 검증
         ├─ 전략 심층 분석 (코드 읽기 포함)
         └─ 중기 제안서 작성 (사용자 동의 후)
```

### 월말 (자동 + 수동)

```
마지막 금  주간 루틴 실행 시 월말 데이터도 자연스럽게 포함

주말     [Cowork] monthly_review.md (사용자와 대화)
           ├─ 월간 쿼리 실행 + 주간 리포트 종합
           ├─ 전략 유효성 검증 (MA, 리스크 파라미터)
           ├─ 사용자와 전략 방향 논의
           └─ docs/reports/YYYY-MM_monthly.md + 전략 제안서
```

## Code vs Cowork 분리 기준

| 판단 기준 | Code (자동) | Cowork (수동) |
|-----------|-------------|---------------|
| 입출력이 정형화됨 | O | - |
| 임계값/룰로 판단 가능 | O | - |
| 소스 코드 읽기 필요 | △ (정형 참조) | O (해석) |
| "왜?"에 답해야 함 | - | O |
| 사용자 동의 필요 | - | O |
| 매일 동일 패턴 | O | - |
| 케이스별 검증 방법 다름 | - | O |

## launchd 설정

기존 `com.kis.autoimplement.plist`를 수정하거나, 별도 plist를 추가한다.

### 옵션 A: 기존 plist에 16:30 추가

`com.kis.autoimplement.plist`의 `StartCalendarInterval`에 16:30 항목을 추가하고,
`run_auto_implement.sh` 상단에서 시간대를 판단해 분석/구현을 분기:

```bash
HOUR=$(date +%H)
if [ "$HOUR" -lt 17 ]; then
  # 16:30 실행 → 일간 분석
  exec scripts/run_daily_analysis.sh
else
  # 17:15 이후 → 제안서 구현
  exec scripts/run_auto_implement.sh (기존 로직)
fi
```

### 옵션 B: 별도 plist 추가 (권장)

`com.kis.dailyanalysis.plist` 를 새로 생성:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kis.dailyanalysis</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/songhansu/IdeaProjects/kis-autotrader/scripts/run_daily_analysis.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <!-- 월~금 16:30 -->
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader/logs/launchd_dailyanalysis.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader/logs/launchd_dailyanalysis.err</string>
</dict>
</plist>
```

주간 분석은 기존 `com.kis.autoimplement.plist`의 금요일 19:00 슬롯을 활용하되, 스크립트를 `run_weekly_analysis.sh`로 변경.

## Cowork 스케줄 변경

| 기존 | 변경 후 |
|------|---------|
| 일간 스케줄 (매일) | **삭제** — launchd `com.kis.dailyanalysis`로 대체 |
| 주간 스케줄 (금) | 프롬프트를 `weekly_review.md` 참조로 변경, **스케줄을 토요일로** |
| 월간 스케줄 (마지막 금) | 프롬프트를 `monthly_review.md` 참조로 변경, **마지막 토/일로** |

Cowork 프롬프트 (주간):
```
이 프로젝트의 docs/prompts/weekly_review.md 파일을 읽고 그 지시사항을 수행해.
```

Cowork 프롬프트 (월간):
```
이 프로젝트의 docs/prompts/monthly_review.md 파일을 읽고 그 지시사항을 수행해.
```

## 레거시 프롬프트

`daily_analysis.md`, `weekly_analysis.md`, `monthly_analysis.md`는 분리 전 통합 프롬프트.
분리 완료 후에도 참조용으로 보존하되, Cowork 스케줄에서는 사용하지 않는다.
향후 안정화되면 삭제 가능.
