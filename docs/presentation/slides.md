---
theme: seriph
title: AI를 운영하는 개발자
info: |
  ## AI 시대, 개발자의 새로운 역할
  도구를 사용하는 사람에서, 시스템을 설계하는 사람으로.
class: text-center
highlighter: shiki
lineNumbers: false
drawings:
  persist: false
transition: slide-left
mdc: true
fonts:
  sans: "Pretendard, Inter"
  serif: "Noto Serif KR"
  mono: "JetBrains Mono"
colorSchema: dark
background: "#0a0a0f"
---

# AI를 운영하는 개발자

<div class="text-2xl opacity-70 mt-4">
코드를 짜는 AI에서, 의사결정을 돕는 AI로
</div>

<div class="abs-bl m-6 text-sm opacity-50">
<div>한수 &middot; 주식회사 퍼닌</div>
<div class="font-mono">2026</div>
</div>

<style>
h1 {
  font-family: 'Noto Serif KR', serif;
  font-weight: 700;
  background: linear-gradient(120deg, #fafafa 30%, #888 80%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.03em;
}

/* === Global Style Overrides === */
:deep(.slidev-layout) {
  --slidev-slide-padding: 2.5rem;
}
:deep(.slidev-layout h1) {
  font-size: 1.8rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 0.25rem;
}
:deep(.slidev-layout h2) {
  font-size: 1.3rem;
  font-weight: 600;
  opacity: 0.85;
}
:deep(.slidev-layout h3) {
  font-size: 1rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.7;
  margin-bottom: 0.5rem;
}
:deep(.slidev-layout p),
:deep(.slidev-layout li) {
  font-size: 0.92rem;
  line-height: 1.6;
}
:deep(.slidev-layout pre) {
  border-radius: 0.5rem;
  border: 1px solid rgba(255,255,255,0.06);
}
:deep(.slidev-layout code) {
  font-size: 0.82rem;
}
:deep(.slidev-page) {
  background: radial-gradient(ellipse at 20% 50%, rgba(15,52,96,0.15) 0%, transparent 70%),
              radial-gradient(ellipse at 80% 80%, rgba(233,69,96,0.06) 0%, transparent 50%),
              #0a0a0f;
}
</style>

---
layout: center
class: text-center
---

# 16:00

<div class="font-mono text-lg opacity-60 mt-8">
어제 장 마감 직후, 제 맥북에서 일어난 일
</div>

---
layout: default
---

# 오후 4시

장이 끝나고 내가 다른 일을 하는 동안

<div class="grid grid-cols-2 gap-8 mt-6">

<div>

```bash
[15:40:02] post_market_job triggered
[15:40:18] DailyPerformance saved
[15:40:21] Calendar event queued (worker)
[15:40:23] Telegram daily summary sent
[16:00:01] Cowork: 일일 리포트 생성 시작
[16:00:47] Querying analytics (PostgreSQL)
[16:02:12] ✓ docs/reports/2026-04-29_daily.md
[16:02:14] ✓ docs/proposals/
              2026-04-29_screening-pipeline.md
[16:02:14] state: ready
[17:00:01] Claude Code: ready 제안서 수집 (1건)
[17:00:08] 안전 게이트 검증 통과
[17:01:33] pytest ✓ | mypy ✓ | ruff ✓
[17:01:35] state: implemented
[17:01:36] launchctl restart com.kis.autotrader
```

</div>

<div class="space-y-3 text-base">

<div class="opacity-50 text-sm mb-2 uppercase tracking-wider">그동안</div>

- 장 마감 후 결산을 끝냈고
- 거래 데이터를 분석해 제안서를 작성했고
- 제안서를 안전 게이트로 검증했고
- 코드를 수정하고 테스트를 돌렸고
- 통과한 것만 자동 배포하고 서비스를 재시작했다

<div class="mt-4 text-sm opacity-40 italic border-t border-white/10 pt-3">
나는 퇴근 후 저녁에 CHANGELOG와 리포트만 읽으면 된다.
</div>

</div>

</div>

---
layout: center
class: text-center
---

<div class="text-7xl font-serif opacity-90">
이게 가능해진 게
</div>

<div class="text-7xl font-serif mt-4">
<span class="text-orange-400">6개월 전입니다.</span>
</div>

<!--
안녕
-->

---
layout: default
---

# 오늘 이야기할 것

<div class="grid grid-cols-2 gap-10 mt-10">

<div class="space-y-8">

<div>
<div class="text-xs font-mono text-orange-400/70 mb-1 tracking-widest">PART 1</div>
<div class="text-lg font-bold">AI 도구 활용의 3단계 진화</div>
<div class="text-sm opacity-60">나는 어디에 있고, 어디로 가는가</div>
</div>

<div>
<div class="text-xs font-mono text-orange-400/70 mb-1 tracking-widest">PART 2</div>
<div class="text-lg font-bold">실전 케이스: 자율 운영 파이프라인</div>
<div class="text-sm opacity-60">오후 4시 시스템의 내부</div>
</div>

<div>
<div class="text-xs font-mono text-orange-400/70 mb-1 tracking-widest">PART 3</div>
<div class="text-lg font-bold">전이 가능한 패턴 5가지</div>
<div class="text-sm opacity-60">당신의 일에 어떻게 적용할 것인가</div>
</div>

</div>

<div class="space-y-8">

<div>
<div class="text-xs font-mono text-orange-400/70 mb-1 tracking-widest">PART 4</div>
<div class="text-lg font-bold">다음 단계: Harness</div>
<div class="text-sm opacity-60">AI 에이전트 팀 아키텍처</div>
</div>

<div>
<div class="text-xs font-mono text-orange-400/70 mb-1 tracking-widest">PART 5</div>
<div class="text-lg font-bold">개발자의 새로운 역할</div>
<div class="text-sm opacity-60">무엇을 갈고닦을 것인가</div>
</div>

<div class="mt-4 p-4 border-l-2 border-orange-400/60 opacity-70 text-sm">
이 발표가 끝나면<br/>
여러분의 워크플로우를 다시 보게 될 것입니다.
</div>

</div>

</div>

---
layout: section
---

# Part 1.

## AI 도구 활용의 3단계 진화

---
layout: default
---

# 질문 하나

<div class="text-3xl mt-12 leading-relaxed">

여러분은 AI를

<span class="text-orange-400 font-bold">사용</span>하시나요,

<span class="text-cyan-400 font-bold">운영</span>하시나요?

</div>

<div class="mt-12 text-base opacity-50">
이 질문의 답이, 앞으로 5년의 커리어를 가른다고 생각합니다.
</div>

---
layout: default
---

# Lv1. 질문하는 개발자

<div class="grid grid-cols-2 gap-8 mt-4">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">HOW IT LOOKS</div>

- ChatGPT/Claude 채팅창에 코드 요청
- 답변을 복붙해서 IDE로 가져옴
- 매번 컨텍스트를 다시 설명

```
나: "Spring Boot에서 Kafka Consumer 어떻게 설정해?"
AI: (일반론적인 코드 제공)
나: "아 우리 프로젝트는 SASL/SCRAM 쓰는데..."
AI: (다시 작성)
나: "그리고 multi-tenant라..."
```

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">LIMITATIONS</div>

<div class="space-y-2 text-sm opacity-80">

- 컨텍스트 재입력 비용
- 일관성 부족 (어제와 오늘 답이 다름)
- 프로젝트 전체 구조 모름
- "AI 답변을 다시 검수"하는 시간 비용

</div>

<div class="mt-6 p-4 bg-orange-500/10 border border-orange-500/20 rounded-lg">
<div class="text-orange-300 text-sm font-semibold">대부분의 개발자가 지금 머무르는 단계</div>
</div>

</div>

</div>

---
layout: default
---

# Lv2. 위임하는 개발자

<div class="grid grid-cols-2 gap-8 mt-4">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">HOW IT LOOKS</div>

- Claude Code, Cursor 같은 에이전트 도구 사용
- 컨텍스트를 도구가 알아서 읽음
- MCP로 외부 시스템 연결 (DB, API, Slack)
- "구현해줘"라고 말하면 파일 단위로 작업

```bash
$ claude "KafkaConsumer에 retry 로직 추가하고
         테스트도 같이 만들어줘"

✓ Reading src/consumer/...
✓ Modifying KafkaConsumer.java
✓ Creating KafkaConsumerTest.java
✓ Running tests... passed
```

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">LIMITATIONS</div>

<div class="space-y-2 text-sm opacity-80">

- **여전히 사람이 트리거해야 함**
- 분석/제안/구현이 한 세션에 섞임
- "오늘 뭘 개선할까"는 사람이 결정
- 반복적 분석 작업이 자동화 안 됨

</div>

<div class="mt-6 p-4 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
<div class="text-cyan-300 text-sm font-semibold">일 잘하는 개발자가 요즘 도달한 단계</div>
</div>

</div>

</div>

---
layout: default
---

# Lv3. 설계하는 개발자

<div class="grid grid-cols-2 gap-8 mt-4">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">HOW IT LOOKS</div>

- 분석과 구현을 **다른 AI 세션에 분리**
- 스케줄러가 AI를 호출 (사람이 아니라)
- 컨텍스트를 **문서 자산**으로 관리
- AI 제안에 **자동 안전 게이트** 적용
- 사람은 **시스템을 설계**하고 **결정**만 한다

```
[자동] 평일 16:00
  └ Cowork: 분석 + 제안서 작성 (state: ready)

[자동] 평일 17:00
  └ Claude Code: ready 제안서 수집
     ├ 안전 게이트 검증 (금지영역/범위/규칙)
     ├ 코드 수정 + pytest/mypy/ruff
     ├ 통과 → implemented + 서비스 재시작
     └ 실패 → git restore + failed
```

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">WHAT CHANGES</div>

<div class="space-y-2 text-sm opacity-80">

- **시간이 자산화**됨 (장 끝난 뒤에도 진척)
- 의사결정의 질이 데이터로 추적됨
- 시스템이 자기 자신을 개선
- 사람은 **상위 레이어**에서 일함

</div>

<div class="mt-6 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
<div class="text-emerald-300 text-sm font-semibold">오늘 이 발표가 도달하길 권하는 단계</div>
</div>

</div>

</div>

---
layout: center
class: text-center
---

<div class="text-xl opacity-50 mb-8 tracking-wider">정리하면</div>

<div class="grid grid-cols-3 gap-6 text-left max-w-3xl mx-auto">

<div class="p-6 border border-white/10 rounded-xl bg-white/[0.02] hover:bg-white/[0.04] transition">
<div class="text-orange-400 font-mono text-xs mb-3 tracking-widest">LV 1</div>
<div class="text-xl font-bold mb-2">질문한다</div>
<div class="text-sm opacity-50">AI에게 물어본다</div>
</div>

<div class="p-6 border border-white/10 rounded-xl bg-white/[0.02] hover:bg-white/[0.04] transition">
<div class="text-cyan-400 font-mono text-xs mb-3 tracking-widest">LV 2</div>
<div class="text-xl font-bold mb-2">위임한다</div>
<div class="text-sm opacity-50">AI에게 일을 시킨다</div>
</div>

<div class="p-6 border border-emerald-500/40 rounded-xl bg-emerald-500/[0.06]">
<div class="text-emerald-400 font-mono text-xs mb-3 tracking-widest">LV 3</div>
<div class="text-xl font-bold mb-2">설계한다</div>
<div class="text-sm opacity-70">AI를 운영하는 시스템을 만든다</div>
</div>

</div>

---
layout: section
---

# Part 2.

## 실전 케이스

### 자율 운영 파이프라인의 내부

---
layout: default
---

# 만든 것

한국투자증권(KIS) OpenAPI 기반 **자동매매 시스템**

<div class="grid grid-cols-2 gap-6 mt-4">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">FEATURES</div>

- 장중 자동 시세 조회 + 전략 기반 매매
- 5종 전략: MA, RSI, MACD, 볼린저, **앙상블**(기본)
- 리스크 관리: 손절, 익절, MDD, 연패 자동 감시
- 종목 스크리닝: 거래량 상위 자동 발굴
- 일일 결산 &rarr; Google Calendar 자동 등록
- Telegram Bot 16종 명령어 (원격 조작)

<div class="text-xs font-mono text-white/40 mb-3 mt-4 tracking-widest">INFRA</div>

- Macbook (24/7, launchd) / PostgreSQL 16 + Redis 7
- APScheduler / Alembic migration

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">AUTOMATION</div>

- **매일 16:00** Cowork 일일 분석 &rarr; 제안서 생성
- **매일 17:00** Claude Code 자동 구현
- **금 16:30** Cowork 주간 리뷰 &rarr; 중기 제안서
- **월말 금 19:00** Cowork 월간 분석 &rarr; 장기 제안서
- **월말 금 20:00** Claude Code 월간 자동 구현
- 안전 게이트 통과 시 서비스 자동 재시작
- 모든 변경 이력은 DB + CHANGELOG (rolling 5건)

<div class="text-xs font-mono text-white/40 mb-3 mt-4 tracking-widest">SCALE</div>

- 427 tests / 36 test files
- 15종 커스텀 예외 클래스
- mypy strict + ruff 통과 강제
- 자동 구현 누적 63건 이상

</div>

</div>

<div class="text-xs opacity-40 mt-2 italic">
본 발표는 시스템의 자동화 패턴에 집중합니다. 매매 전략 자체는 주제가 아닙니다.
</div>

---
layout: default
---

# 시스템 구성도

<div class="mt-2 flex justify-center">
  <img src="/Flowchart_TB.png" class="h-[460px] object-contain rounded-lg border border-white/5" />
</div>

<div class="mt-2 text-xs opacity-40 text-center">
KIS API &rarr; Trading Engine &rarr; DB &rarr; Cowork 분석 &rarr; Claude Code 구현 &rarr; 안전 게이트 &rarr; 서비스 재시작
</div>

---
layout: default
---

# 핵심 원리 1 &mdash; 역할 분리

<div class="text-base mt-2 opacity-60">
하나의 AI에게 모든 걸 시키지 않는다.
</div>

<div class="grid grid-cols-2 gap-6 mt-4">

<div class="p-5 border border-cyan-500/20 rounded-xl bg-cyan-500/[0.04]">

<div class="text-xs font-mono text-cyan-400/70 mb-2 tracking-widest">COWORK &mdash; 분석 / 제안</div>

<div class="text-sm space-y-1 opacity-80">

- **Claude Desktop** 세션에서 스케줄 실행
- 평일 16:00 일일, 금 16:30 주간, 월말 금 19:00 월간
- `query_analytics.py`로 거래/시그널/스크리닝 JSON 조회
- 일일/주간/월간 리포트 자동 생성
- `docs/proposals/YYYY-MM-DD_제목.md` 출력
- 상태는 `ready`로 시작, Claude Code가 받음
- **코드는 직접 안 건드림**

</div>

</div>

<div class="p-5 border border-orange-500/20 rounded-xl bg-orange-500/[0.04]">

<div class="text-xs font-mono text-orange-400/70 mb-2 tracking-widest">CLAUDE CODE &mdash; 구현 / 테스트</div>

<div class="text-sm space-y-1 opacity-80">

- 평일 17:00 / 월말 금 20:00 launchd로 자동 실행 (Claude Code CLI)
- `BRIDGE_SPEC.md`의 안전 게이트 자동 검증
- 통과한 제안서만 코드 수정 &rarr; pytest/mypy/ruff
- 통과 시 `implemented`, 실패 시 `git restore`
- DB `implementation_logs` + CHANGELOG 자동 기록
- **분석은 직접 안 함**

</div>

</div>

</div>

<div class="mt-4 p-3 border-l-2 border-emerald-400/60 text-sm opacity-70">
<strong>왜 분리하는가:</strong> 분석은 데이터/시간 컨텍스트가, 구현은 코드 컨텍스트가 필요하다.
한 세션에 섞으면 둘 다 흐려진다. <strong>역할이 다르면 세션도 달라야 한다.</strong>
</div>

---
layout: default
---

# 핵심 원리 2 &mdash; 컨텍스트는 자산이다

<div class="text-sm opacity-50 mb-2">프로젝트에 두는 문서들</div>

<div class="grid grid-cols-2 gap-6">

<div>

```
project-root/
├── CLAUDE.md              ← AI 진입점
├── docs/
│   ├── BRIDGE_SPEC.md     ← Cowork↔Code 규격
│   ├── CHANGELOG.md       ← 최근 5건 rolling
│   ├── reports/
│   │   ├── 04-29_daily.md
│   │   └── W17_weekly.md
│   └── proposals/
│       ├── 04-29_screening
│       │   -pipeline-fix.md
│       └── 04-30_screening
│           -query-tz-fix.md
├── src/
└── tests/
+ DB: implementation_logs (영구 저장)
```

</div>

<div class="space-y-2 text-xs">

<div>
<span class="font-bold text-emerald-400">CLAUDE.md</span> &mdash;
<span class="opacity-70">프로젝트 목적, 디렉토리 구조, 코딩 컨벤션, 모듈 경계, API 호출 정책. AI가 가장 먼저 읽음.</span>
</div>

<div>
<span class="font-bold text-emerald-400">BRIDGE_SPEC.md</span> &mdash;
<span class="opacity-70">Cowork&harr;Code 자동화 규격. 안전 게이트 규칙(금지 영역, 25개 파라미터 허용 범위) 명시.</span>
</div>

<div>
<span class="font-bold text-emerald-400">reports/</span> &mdash;
<span class="opacity-70">Cowork가 자동 생성하는 일일/주간/월간 리포트. 사람도 읽고 다음 날 Cowork도 컨텍스트로 읽음.</span>
</div>

<div>
<span class="font-bold text-emerald-400">proposals/</span> &mdash;
<span class="opacity-70">AI가 만든 제안과 사람의 결정이 누적되는 의사결정 아카이브. 파일명에 날짜+주제 명시.</span>
</div>

<div>
<span class="font-bold text-emerald-400">implementation_logs (DB)</span> &mdash;
<span class="opacity-70">전체 변경 이력의 영구 저장소. CHANGELOG는 최근 5건만 rolling으로 유지.</span>
</div>

</div>

</div>

<div class="mt-3 p-3 border-l-2 border-emerald-400/60 text-sm opacity-70">
<strong>핵심:</strong> AI에게 매번 컨텍스트를 말로 설명하지 않는다.
<strong>문서를 잘 정리하면, AI는 알아서 그걸 읽는다.</strong>
</div>

---
layout: default
---

# 핵심 원리 3 &mdash; 로그가 아니라 데이터다

<div class="grid grid-cols-2 gap-8 mt-4">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">BEFORE &mdash; 로그 파일 시대</div>

```
2026-04-28 09:32:11 [INFO] BUY signal triggered
2026-04-28 09:32:11 [INFO] Symbol: 005930
2026-04-28 09:32:12 [INFO] Volume: 100
2026-04-28 09:32:14 [INFO] Order placed: ord_8821
2026-04-28 09:32:15 [INFO] Filled at 78,400
...
```

<div class="mt-3 text-sm opacity-60">
AI에게 "지난주 손절 평균 손실률 알려줘"라고 하면<br/>
&rarr; grep, 정규식, 파싱... 매번 깨짐
</div>

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">AFTER &mdash; 구조화된 DB + 분석 쿼리</div>

```bash
$ python scripts/query_analytics.py risk --days 7
```

```json
{
  "stop_loss":   { "count": 8, "avg": -2.15 },
  "take_profit": { "count": 10, "avg": 3.45 },
  "recommendation": {
    "stop_loss_rate":  0.0215,
    "take_profit_rate": 0.0345
  }
}
```

<div class="mt-3 text-sm opacity-60">
Cowork가 이 JSON을 직접 파싱해<br/>
"손절률을 0.025로 조정 제안" 같은 결론을 도출.
</div>

</div>

</div>

<div class="mt-4 p-3 border-l-2 border-emerald-400/60 text-sm opacity-70">
<strong>교훈:</strong> AI에게 분석을 시키려면, AI가 <em>질문할 수 있는 형태</em>로 데이터를 둬야 한다.
로그는 사람을 위한 것, <strong>구조화된 쿼리 출력은 AI를 위한 것</strong>이다.
</div>

---
layout: default
---

# 핵심 원리 4 &mdash; 안전 게이트

<div class="text-sm opacity-50 mb-2">AI가 만든 제안을 그대로 머지하지 않는다</div>

<div class="grid grid-cols-4 gap-2 mt-2">

<div class="p-3 border border-white/10 rounded-lg">
<div class="text-white/40 font-mono text-[10px] mb-1 tracking-widest">STATE</div>
<div class="text-sm font-bold mb-1">ready</div>
<div class="text-[11px] opacity-60">Cowork 작성 완료. Claude Code가 즉시 처리 가능.</div>
</div>

<div class="p-3 border border-emerald-500/30 rounded-lg bg-emerald-500/[0.04]">
<div class="text-emerald-400 font-mono text-[10px] mb-1 tracking-widest">STATE</div>
<div class="text-sm font-bold mb-1">implemented</div>
<div class="text-[11px] opacity-60">코드 수정 + pytest/mypy/ruff 통과 + 서비스 재시작.</div>
</div>

<div class="p-3 border border-red-500/30 rounded-lg bg-red-500/[0.04]">
<div class="text-red-400 font-mono text-[10px] mb-1 tracking-widest">STATE</div>
<div class="text-sm font-bold mb-1">failed</div>
<div class="text-[11px] opacity-60">테스트 실패. git restore 원복. Cowork가 재검토.</div>
</div>

<div class="p-3 border border-amber-500/30 rounded-lg bg-amber-500/[0.04]">
<div class="text-amber-400 font-mono text-[10px] mb-1 tracking-widest">STATE</div>
<div class="text-sm font-bold mb-1">skipped</div>
<div class="text-[11px] opacity-60">안전 규칙 위반. 자동 스킵.</div>
</div>

</div>

<div class="grid grid-cols-3 gap-3 mt-4">

<div class="p-3 border-l-2 border-red-400/60">
<div class="font-bold text-red-300 text-xs mb-1">금지 영역</div>
<div class="text-[11px] opacity-70 space-y-0.5">
<div>.env 직접 수정 / credentials, token.json</div>
<div>KIS_ENV 모의&rarr;실전 / alembic 마이그레이션</div>
<div>외부 패키지 추가</div>
</div>
</div>

<div class="p-3 border-l-2 border-amber-400/60">
<div class="font-bold text-amber-300 text-xs mb-1">파라미터 범위</div>
<div class="text-[11px] opacity-70 space-y-0.5">
<div>25개 파라미터 허용 범위 명시</div>
<div>예: MAX_LOSS_RATE 0.01~0.05</div>
<div>config_overrides.json으로만 / 가중치 합=1.0</div>
</div>
</div>

<div class="p-3 border-l-2 border-cyan-400/60">
<div class="font-bold text-cyan-300 text-xs mb-1">코드 변경 규칙</div>
<div class="text-[11px] opacity-70 space-y-0.5">
<div>제안서당 최대 5개 파일 / 파일 삭제 금지</div>
<div>신규 파일은 src/strategy, tests만</div>
<div>시그니처 변경 시 테스트 동반 필수</div>
</div>
</div>

</div>

<div class="mt-3 p-2 border-l-2 border-emerald-400/60 text-xs opacity-60">
<strong>핵심:</strong> "AI에게 위임" &ne; "AI에게 무조건 맡김". 코드로 검증되는 규칙이 사람의 승인을 대신한다.
</div>

---
layout: default
---

# 데모 &mdash; 실제 제안서와 자동 구현

<div class="grid grid-cols-2 gap-4 mt-3">

<div>

```markdown {*}{maxHeight:'360px'}
# 스크리닝 DB 조회 타임존 불일치 수정

## 메타데이터

- 작성: Cowork
- 일자: 2026-04-30
- 상태: ready
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/db/repository.py

## 현상 분석

get_by_date()가 naive datetime을 사용해
KST 경계에서 누락 발생.
일별 스크리닝 결과 일부가 조회되지 않음.

## 변경 스펙

src/db/repository.py:
  datetime.combine(target_date, ...,
  tzinfo=kst) 적용

tests/test_db/test_repository.py:
  KST 타임존 기반 테스트 2건 추가

## 롤백

git restore src/db/repository.py
```

</div>

<div class="space-y-3">

<div class="text-xs font-mono text-white/40 mb-2 tracking-widest">WHAT THE PROPOSAL DID</div>

<div class="space-y-1.5 text-sm">
<div><span class="text-emerald-400">&#10003;</span> Cowork가 거래 분석 중 <strong>스스로 발견</strong></div>
<div><span class="text-emerald-400">&#10003;</span> <strong>관련 파일</strong>까지 명시</div>
<div><span class="text-emerald-400">&#10003;</span> 테스트 추가까지 <strong>변경 스펙에 포함</strong></div>
<div><span class="text-emerald-400">&#10003;</span> <strong>롤백 방법</strong>도 함께 작성</div>
</div>

<div class="text-xs font-mono text-white/40 mb-2 mt-4 tracking-widest">WHAT CLAUDE CODE DID (17:00)</div>

```bash
✓ 안전 게이트 통과 (파일 2개, 모두 허용 영역)
✓ src/db/repository.py 수정
✓ 테스트 2건 추가
✓ pytest: 423 passed
✓ mypy: pre-existing only
✓ ruff: pre-existing only
✓ state: implemented
✓ launchctl restart com.kis.autotrader
```

<div class="mt-3 p-2 border border-amber-500/20 rounded-lg bg-amber-500/[0.04] text-xs">
실제 2026-04-30 CHANGELOG 첫 줄.<br/>
이 변경에 들어간 <strong>내 시간: 0초.</strong>
</div>

</div>

</div>

---
layout: section
---

# Part 3.

## 전이 가능한 패턴 5가지

<div class="text-base opacity-50 mt-4">
트레이딩이 아니어도 적용 가능한 일반 원리
</div>

---
layout: default
---

# 패턴 1. 컨텍스트 파일을 자산처럼 관리하라

<div class="grid grid-cols-2 gap-8 mt-6">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">USE CASES</div>

- **사내 시스템 운영**: `RUNBOOK.md`로 장애 대응 절차 자동화
- **레거시 인수**: `ARCHITECTURE.md`로 AI에게 "이 시스템의 역사" 학습
- **온보딩**: 신입에게 주는 문서 = AI에게도 좋은 컨텍스트

<div class="text-xs font-mono text-white/40 mb-3 mt-6 tracking-widest">HOW TO</div>

```
1. CLAUDE.md를 README와 별도로 만들어라
2. AI가 자주 틀리는 부분을 거기에 적어라
3. 변경되면 코드처럼 PR로 관리하라
4. 팀이 같이 편집하라
```

</div>

<div class="p-6 border-l-2 border-emerald-400/60 bg-emerald-500/[0.03] rounded-r-xl flex items-center">

<div class="text-xl leading-relaxed">
"AI에게 매번 설명하는 내용"을<br/>
<strong>문서로 저장</strong>하면<br/>
그 문서가 <strong>팀의 자산</strong>이 된다.
</div>

</div>

</div>

---
layout: default
---

# 패턴 2. 분석과 실행을 분리하라

<div class="grid grid-cols-2 gap-8 mt-6">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">USE CASES</div>

- **장애 분석**: 분석 AI는 메트릭/로그만, 실행 AI는 인프라만
- **코드 리뷰**: 리뷰 AI는 패턴 분석, 수정 AI는 코드 작성
- **고객 응대**: 분류 AI &rarr; 답변 AI &rarr; 검수 AI 파이프라인

<div class="text-xs font-mono text-white/40 mb-3 mt-6 tracking-widest">ANTI-PATTERN</div>

```
한 세션에서 하지 말 것:
"우리 시스템 분석하고
 문제 찾고
 코드 고치고
 테스트도 만들어줘"

→ 어느 것도 깊이 못 한다
```

</div>

<div class="p-6 border-l-2 border-emerald-400/60 bg-emerald-500/[0.03] rounded-r-xl flex items-center">

<div class="text-xl leading-relaxed">
역할이 다른 AI 세션은<br/>
<strong>다른 사람</strong>으로 대해라.<br/>
한 명에게 다 시키면<br/>
어느 것도 잘 못한다.
</div>

</div>

</div>

---
layout: default
---

# 패턴 3. AI가 질문할 수 있는 형태로 데이터를 두라

<div class="mt-4 text-sm opacity-60 mb-4">
실제로 이 시스템에서 Cowork가 매일 실행하는 쿼리
</div>

<div class="grid grid-cols-2 gap-6">

<div>

<div class="text-xs font-mono text-red-400/60 mb-2 tracking-widest">BEFORE &mdash; 사람이 로그를 읽던 시절</div>

```
$ grep "STOP_LOSS" logs/autotrader.log | wc -l
8
$ grep "STOP_LOSS" logs/autotrader.log | ???
# 평균 손실률? 파싱 불가능...
```

<div class="text-xs opacity-50 mt-2">
AI에게 시켜도 "정규식으로 파싱하겠습니다"<br/>
&rarr; 로그 포맷 바뀌면 즉시 깨짐
</div>

</div>

<div>

<div class="text-xs font-mono text-emerald-400/60 mb-2 tracking-widest">AFTER &mdash; AI가 SQL/JSON으로 질문</div>

```bash
$ python scripts/query_analytics.py risk --days 7
```

```json
{
  "stop_loss": { "count": 8, "avg": -2.15 },
  "recommendation": {
    "stop_loss_rate": 0.0215
  }
}
```

<div class="text-xs opacity-50 mt-2">
Cowork가 이 JSON을 파싱해<br/>
<strong>"손절률을 0.025로 조정"</strong> 제안서를 자동 작성
</div>

</div>

</div>

<div class="mt-4 p-3 border border-emerald-500/20 rounded-lg bg-emerald-500/[0.03] text-center text-sm">
<strong>판단 기준:</strong> AI에게 분석을 시킬 때 grep이 필요하면, 데이터 구조를 다시 설계해야 한다.
</div>

---
layout: default
---

# 패턴 4. AI 위임에는 검증 가능한 규칙이 있어야 한다

<div class="grid grid-cols-2 gap-8 mt-6">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">USE CASES</div>

- **자동 문서화**: 소스 변경 없는 영역만 허용
- **코드 리팩토링**: 동작 동일 보장 + 테스트 통과 강제
- **API 스펙 변경**: 외부 영향 &rarr; 자동화 영역에서 제외
- **데이터 마이그레이션**: 되돌릴 수 없음 &rarr; 항상 사람 검토

<div class="text-xs font-mono text-white/40 mb-3 mt-6 tracking-widest">GATE DESIGN</div>

```
1. 무엇을 절대 건드리지 않는가? (금지 영역)
2. 어디까지 자동으로 변경 가능한가? (허용 범위)
3. 검증은 어떻게 자동화되는가? (테스트/린트)
4. 실패 시 어떻게 원복되는가? (rollback)
```

</div>

<div class="p-6 border-l-2 border-emerald-400/60 bg-emerald-500/[0.03] rounded-r-xl flex items-center">

<div class="text-xl leading-relaxed">
"AI를 신뢰하는가"는<br/>
잘못된 질문이다.<br/>
<br/>
"<strong>코드로 검증되는 경계</strong>가<br/>
어디인가"가<br/>
올바른 질문이다.
</div>

</div>

</div>

---
layout: default
---

# 패턴 5. 반복 루틴은 스케줄러에 넘겨라

<div class="mt-4 text-sm opacity-60 mb-4">
맥북에서 돌고 있는 스케줄러 &mdash; launchd 6개 + Claude Desktop 3개
</div>

```bash
$ launchctl list | grep com.kis
com.kis.autotrader         # 매매 엔진 (24/7)
com.kis.watchdog           # 프로세스 감시 (5분마다)
com.kis.autoimplement      # Claude Code 일일 자동 구현 (평일 17:00)
com.kis.monthlyimplement   # Claude Code 월간 자동 구현 (월말 금 20:00)
com.kis.dashboard          # Streamlit 대시보드 (24/7)
com.kis.backup-db          # DB 백업 (매일, 7일 롤링)

# Claude Desktop 스케줄러 (Cowork 세션)
- 일일 분석     평일 16:00
- 주간 리뷰     금 16:30
- 월간 분석     월말 금 19:00
```

<div class="grid grid-cols-2 gap-6 mt-4">

<div class="space-y-2 text-sm">

<div class="text-xs font-mono text-white/40 mb-2 tracking-widest">YOUR VERSION</div>

- **매일**: 배포 영향 분석, 메트릭 리포트
- **매주**: PR/이슈 트렌드 요약
- **매월**: 의존성 보안 스캔 + 제안
- **분기**: 코드베이스 health check

</div>

<div class="p-5 border border-emerald-500/20 rounded-xl bg-emerald-500/[0.03] flex items-center">

<div class="text-lg leading-relaxed">
"AI 써야지" 하고 사람이 매번 트리거하면 결국 안 쓰게 된다.<br/>
<strong>AI는 스케줄러가 깨워야 한다.</strong>
</div>

</div>

</div>

---
layout: center
class: text-center
---

# 5가지 패턴, 한 장 요약

<div class="grid grid-cols-5 gap-3 mt-8 text-left max-w-4xl mx-auto">

<div class="p-4 border border-white/10 rounded-xl bg-white/[0.02]">
<div class="text-emerald-400 font-mono text-[10px] mb-2 tracking-widest">PATTERN 1</div>
<div class="text-sm font-bold mb-1">컨텍스트 자산화</div>
<div class="text-xs opacity-50">매번 설명 &rarr; 문서</div>
</div>

<div class="p-4 border border-white/10 rounded-xl bg-white/[0.02]">
<div class="text-emerald-400 font-mono text-[10px] mb-2 tracking-widest">PATTERN 2</div>
<div class="text-sm font-bold mb-1">역할 분리</div>
<div class="text-xs opacity-50">분석 &ne; 실행</div>
</div>

<div class="p-4 border border-white/10 rounded-xl bg-white/[0.02]">
<div class="text-emerald-400 font-mono text-[10px] mb-2 tracking-widest">PATTERN 3</div>
<div class="text-sm font-bold mb-1">구조화된 데이터</div>
<div class="text-xs opacity-50">grep &rarr; SQL/JSON</div>
</div>

<div class="p-4 border border-white/10 rounded-xl bg-white/[0.02]">
<div class="text-emerald-400 font-mono text-[10px] mb-2 tracking-widest">PATTERN 4</div>
<div class="text-sm font-bold mb-1">검증 가능한 규칙</div>
<div class="text-xs opacity-50">신뢰 &rarr; 검증</div>
</div>

<div class="p-4 border border-white/10 rounded-xl bg-white/[0.02]">
<div class="text-emerald-400 font-mono text-[10px] mb-2 tracking-widest">PATTERN 5</div>
<div class="text-sm font-bold mb-1">스케줄 트리거</div>
<div class="text-xs opacity-50">사람 &ne; 시작 버튼</div>
</div>

</div>

<div class="mt-12 text-lg opacity-60">
이 다섯 가지가 합쳐지면 &mdash; <span class="text-emerald-400 font-bold">자율 운영 파이프라인</span>이 된다.
</div>

---
layout: section
---

# Part 4.

## 다음 단계: Harness

### AI 에이전트 팀을 설계하는 아키텍처

---
layout: default
---

# 왜 Harness인가 &mdash; 스크립트 기반의 한계

<div class="text-sm mt-2 opacity-60">
지금 우리 시스템은 잘 돌아간다. 그런데 한 발 더 나가면 어디서 막히는가?
</div>

<div class="grid grid-cols-2 gap-6 mt-5">

<div class="p-5 border border-red-500/20 rounded-xl bg-red-500/[0.03]">

<div class="text-xs font-mono text-red-400/70 mb-2 tracking-widest">LV3의 천장 (지금 우리)</div>

<div class="text-sm space-y-2 opacity-85">

- 역할 분리는 **쉘 스크립트**로 한다 (`run_daily_analysis.sh`)
- 에이전트 간 통신은 **파일**(`proposals/`)로 한다
- 작업 의존성은 **launchd 시간표**로 한다 (16:00 → 17:00)
- 새 역할(예: 보안 감사) 추가 = 새 스크립트 + 새 cron + 새 디렉토리
- 한 번 실패하면 **사람이 로그를 읽고** 다음 cron까지 기다림

</div>

<div class="text-xs opacity-50 italic mt-3">
"AI를 운영"하지만, 운영의 뼈대는 여전히 사람이 만든 스크립트다.
</div>

</div>

<div class="p-5 border border-emerald-500/20 rounded-xl bg-emerald-500/[0.03]">

<div class="text-xs font-mono text-emerald-400/70 mb-2 tracking-widest">HARNESS가 푸는 문제</div>

<div class="text-sm space-y-2 opacity-85">

- 역할은 **선언적인 마크다운**으로 정의한다
- 통신은 **에이전트 간 메시지 프로토콜**로 한다
- 의존성은 **태스크 그래프**로 표현한다 (시간이 아니라)
- 새 역할 추가 = **에이전트 파일 한 장**
- 실패하면 **다른 에이전트가 자동으로 진단**한다

</div>

<div class="text-xs opacity-50 italic mt-3">
"AI 팀을 운영하는 OS"를 갖는다는 것.
</div>

</div>

</div>

<div class="mt-4 p-3 border-l-2 border-orange-400/60 text-sm opacity-70">
<strong>한 줄로:</strong> Lv3는 "AI를 부리는 사람"이다. Harness는 "AI 팀을 부리는 AI"를 만든다.
</div>

---
layout: default
---

# Harness의 3계층 &mdash; 누가 / 어떻게 / 언제

<div class="text-sm mt-1 opacity-60">
사람을 채용해 팀을 만드는 과정과 똑같다. 역할 정의(Job Description) → 매뉴얼(SOP) → 매니저(PM).
</div>

<div class="grid grid-cols-3 gap-3 mt-4">

<div class="p-4 border border-cyan-500/20 rounded-xl bg-cyan-500/[0.03]">

<div class="text-xs font-mono text-cyan-400/70 mb-2 tracking-widest">1. AGENT &mdash; 누가</div>

<div class="text-xs opacity-50 mb-2">"이 사람은 어떤 사람인가"</div>

```
.claude/agents/
  market-analyst.md
  risk-reviewer.md
  code-implementer.md
  qa-verifier.md
```

<div class="text-xs opacity-70 mt-2 space-y-1">

- **정체성**: 직무, 책임 범위
- **원칙**: 절대 안 하는 것
- **입출력**: 받는 데이터 / 만드는 결과
- **협업**: 누구에게 위임 / 누구의 검증

</div>

<div class="text-[11px] opacity-40 mt-2 italic">
사람으로 치면 "직무기술서"
</div>

</div>

<div class="p-4 border border-emerald-500/20 rounded-xl bg-emerald-500/[0.03]">

<div class="text-xs font-mono text-emerald-400/70 mb-2 tracking-widest">2. SKILL &mdash; 어떻게</div>

<div class="text-xs opacity-50 mb-2">"이 일은 어떻게 하는가"</div>

```
.claude/skills/
  trading-analysis/
    skill.md         (SOP)
    references/      (사례)
    scripts/         (도구)
```

<div class="text-xs opacity-70 mt-2 space-y-1">

- **수행 방법**: 단계, 체크리스트
- **점진적 공개**: 필요할 때만 상세 로드
- **재사용**: 1 스킬 → N 에이전트
- **버전 관리**: 코드처럼

</div>

<div class="text-[11px] opacity-40 mt-2 italic">
사람으로 치면 "업무 매뉴얼/SOP"
</div>

</div>

<div class="p-4 border border-orange-500/20 rounded-xl bg-orange-500/[0.03]">

<div class="text-xs font-mono text-orange-400/70 mb-2 tracking-widest">3. ORCHESTRATOR &mdash; 언제</div>

<div class="text-xs opacity-50 mb-2">"누가 언제 일하는가"</div>

```
태스크 그래프
  ├ 의존성 분석
  ├ 병렬 가능 식별
  ├ 결과 수집/통합
  └ 실패 시 폴백
```

<div class="text-xs opacity-70 mt-2 space-y-1">

- **분배**: 누구에게 어떤 작업
- **순서**: 무엇이 먼저
- **합산**: 결과 어떻게 모음
- **회복**: 실패 시 어떻게

</div>

<div class="text-[11px] opacity-40 mt-2 italic">
사람으로 치면 "PM/팀장"
</div>

</div>

</div>

<div class="mt-3 p-2 border-l-2 border-emerald-400/60 text-xs opacity-65">
<strong>핵심:</strong> 셋은 분리되어야 한다. Agent에 Skill 내용을 박으면 재사용이 깨지고, Orchestrator에 역할을 박으면 팀 확장이 막힌다.
</div>

---
layout: default
---

# Agent 파일 &mdash; 어떻게 생겼나

<div class="text-sm mt-1 opacity-60">
실제 Agent 정의 파일은 마크다운 한 장이다. 코드가 아니라 <strong>선언</strong>이다.
</div>

<div class="grid grid-cols-2 gap-5 mt-4">

<div>

```markdown {*}{maxHeight:'380px'}
---
name: market-analyst
description: 장 마감 후 거래 데이터를
  분석해 개선 제안서를 작성하는 분석가.
model: sonnet
tools: [Read, Bash, Grep]
---

# 정체성

당신은 KIS 자동매매 시스템의 시장 분석가입니다.
거래 데이터에서 패턴과 개선점을 찾는 것이
유일한 책임입니다.

# 절대 원칙

- 코드(src/, tests/)는 절대 수정하지 않는다
- .env, credentials.json은 읽지도 않는다
- 추측이 아닌 query_analytics.py 출력만 근거로
  사용한다

# 입력

- docs/reports/ (어제까지의 리포트)
- query_analytics.py 의 JSON 출력
- BRIDGE_SPEC.md (안전 게이트 규칙)

# 출력

- docs/proposals/YYYY-MM-DD_제목.md
  (state: ready, BRIDGE_SPEC 준수)

# 협업

- 제안 후 code-implementer 에이전트가 받는다
- 안전 게이트 통과 못 할 제안은 만들지 않는다
```

</div>

<div class="text-sm space-y-3">

<div class="text-xs font-mono text-white/40 mb-2 tracking-widest">ANATOMY</div>

<div>
<span class="text-cyan-400 font-bold">frontmatter</span>
<div class="text-xs opacity-65 mt-0.5">에이전트 메타데이터. 모델, 사용 가능한 도구, 호출 시 자동 매칭에 쓰이는 description.</div>
</div>

<div>
<span class="text-cyan-400 font-bold">정체성 / 절대 원칙</span>
<div class="text-xs opacity-65 mt-0.5">"이 사람은 누구인가"와 "절대 하지 않는 것". CLAUDE.md의 전역 규칙을 이 역할에 맞게 좁힌다.</div>
</div>

<div>
<span class="text-cyan-400 font-bold">입력 / 출력</span>
<div class="text-xs opacity-65 mt-0.5">에이전트 간 통신 프로토콜. 파일 경로/형식까지 명시해야 다른 에이전트가 이어받을 수 있다.</div>
</div>

<div>
<span class="text-cyan-400 font-bold">협업</span>
<div class="text-xs opacity-65 mt-0.5">앞뒤 에이전트와의 인터페이스. 이게 곧 Orchestrator가 그릴 그래프의 간선이다.</div>
</div>

<div class="mt-4 p-3 border-l-2 border-emerald-400/60 text-xs opacity-70">
지금 우리 프로젝트의 <strong>BRIDGE_SPEC.md + CLAUDE.md의 모듈 경계</strong>를 에이전트 단위로 쪼개면 그대로 이 파일들이 된다.
</div>

</div>

</div>

---
layout: default
---

# Skill &mdash; 점진적 정보 공개

<div class="text-sm mt-1 opacity-60">
스킬은 "이 작업을 어떻게 수행하는가"를 단계적으로 펼쳐 보여주는 매뉴얼이다.
</div>

<div class="grid grid-cols-2 gap-6 mt-4">

<div>

```
.claude/skills/safety-gate/
├── skill.md            ← 항상 로드 (요약)
├── references/
│   ├── forbidden.md    ← 금지 영역 상세
│   ├── ranges.md       ← 25개 파라미터 표
│   └── examples.md     ← 통과/실패 사례
└── scripts/
    ├── validate.py     ← 자동 검증 도구
    └── rollback.sh     ← 실패 시 원복
```

<div class="text-xs opacity-50 mt-3 space-y-1">

- <strong>skill.md</strong>는 짧게 (수십 줄). 트리거 조건과 핵심 원칙만.
- <strong>references/</strong>는 필요할 때만 읽는다. 컨텍스트 비용을 아낀다.
- <strong>scripts/</strong>는 LLM이 직접 짜지 않고 호출하는 결정적 도구.

</div>

</div>

<div class="space-y-3">

<div class="text-xs font-mono text-white/40 mb-2 tracking-widest">WHY 점진적 공개</div>

<div class="p-3 border border-white/10 rounded-lg text-sm">
<div class="font-bold text-emerald-400 mb-1">컨텍스트 한계 우회</div>
<div class="text-xs opacity-70">25개 파라미터 표 전체를 매번 읽지 않는다. "범위 검증 필요할 때만" references/ranges.md를 연다.</div>
</div>

<div class="p-3 border border-white/10 rounded-lg text-sm">
<div class="font-bold text-emerald-400 mb-1">재사용성</div>
<div class="text-xs opacity-70">safety-gate 스킬은 code-implementer, qa-verifier, auto-heal 모두가 같이 쓴다. 1개 스킬, N개 에이전트.</div>
</div>

<div class="p-3 border border-white/10 rounded-lg text-sm">
<div class="font-bold text-emerald-400 mb-1">결정성</div>
<div class="text-xs opacity-70">검증 같은 결정적 로직은 LLM이 매번 다시 짜지 않고 scripts/ 도구를 호출한다. <strong>비결정성을 코드로 격리</strong>한다.</div>
</div>

<div class="p-3 border border-white/10 rounded-lg text-sm">
<div class="font-bold text-emerald-400 mb-1">버전 관리</div>
<div class="text-xs opacity-70">스킬도 PR로 리뷰. "이 스킬이 어떻게 바뀌어 왔나"가 git에 남는다.</div>
</div>

</div>

</div>

---
layout: default
---

# Orchestrator &mdash; 4가지 협업 패턴

<div class="text-sm mt-1 opacity-60">
같은 에이전트들도, 어떻게 엮느냐에 따라 결과가 달라진다.
</div>

<div class="grid grid-cols-2 gap-4 mt-4">

<div class="p-4 border border-cyan-500/20 rounded-xl bg-cyan-500/[0.03]">
<div class="font-bold text-cyan-400 text-sm mb-2">파이프라인 (Sequential)</div>
<div class="font-mono text-xs opacity-70 mb-2">analyst → implementer → qa</div>
<div class="text-xs opacity-65">앞 단계 결과가 뒷 단계 입력. <strong>지금 우리 시스템</strong>이 정확히 이 모양 (16:00 → 17:00).</div>
<div class="text-[11px] opacity-40 mt-2 italic">언제: 단계가 명확하고 의존성이 강할 때</div>
</div>

<div class="p-4 border border-emerald-500/20 rounded-xl bg-emerald-500/[0.03]">
<div class="font-bold text-emerald-400 text-sm mb-2">팬아웃 / 팬인 (Parallel)</div>
<div class="font-mono text-xs opacity-70 mb-2">분석가 3명 병렬 → 통합자 1명</div>
<div class="text-xs opacity-65">market-analyst, risk-analyst, performance-analyst가 <strong>동시에</strong> 분석 → synthesizer가 합침.</div>
<div class="text-[11px] opacity-40 mt-2 italic">언제: 독립적 관점들이 모여야 할 때</div>
</div>

<div class="p-4 border border-orange-500/20 rounded-xl bg-orange-500/[0.03]">
<div class="font-bold text-orange-400 text-sm mb-2">생성-검증 (Generator-Critic)</div>
<div class="font-mono text-xs opacity-70 mb-2">implementer ⇄ qa (반복)</div>
<div class="text-xs opacity-65">구현 → QA 지적 → 재구현 → 재검증. <strong>실패가 학습</strong>이 된다. 90% 임계까지 자동 반복.</div>
<div class="text-[11px] opacity-40 mt-2 italic">언제: 품질 기준이 높고 한 번에 못 맞출 때</div>
</div>

<div class="p-4 border border-amber-500/20 rounded-xl bg-amber-500/[0.03]">
<div class="font-bold text-amber-400 text-sm mb-2">감독자 (Supervisor)</div>
<div class="font-mono text-xs opacity-70 mb-2">supervisor → 동적으로 선택</div>
<div class="text-xs opacity-65">상황 보고 supervisor가 <strong>그때그때 적절한 에이전트를 선택</strong>. 장애 상황처럼 미리 정할 수 없을 때.</div>
<div class="text-[11px] opacity-40 mt-2 italic">언제: 작업 구조가 사전에 결정 안 될 때</div>
</div>

</div>

<div class="mt-3 p-2 border-l-2 border-emerald-400/60 text-xs opacity-65">
<strong>현실에서는 섞인다:</strong> 메인은 파이프라인, 분석 단계 안에서는 팬아웃, 구현 단계는 생성-검증, 장애 발생 시 감독자.
</div>

---
layout: default
---

# 우리 시스템에 Harness를 적용한다면

<div class="grid grid-cols-2 gap-8 mt-4">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">CURRENT &mdash; 스크립트 기반</div>

```
launchd
  ├ 16:00 → run_daily_analysis.sh
  │         (Cowork 단일 세션)
  ├ 17:00 → run_auto_implement.sh
  │         (Claude Code 단일 세션)
  └ 5분마다 → watchdog.sh
              (auto_heal.sh)
```

<div class="mt-3 text-sm opacity-60">
각 세션이 독립적으로 실행<br/>
역할은 스크립트로 분리<br/>
에이전트 간 통신은 파일 기반 (proposals/)
</div>

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">NEXT &mdash; HARNESS 적용 시</div>

```
.claude/agents/
  market-analyst.md    # 시장 분석
  risk-reviewer.md     # 리스크 검토
  code-implementer.md  # 코드 구현
  qa-verifier.md       # 품질 검증

.claude/skills/
  trading-analysis/    # 매매 분석 방법
  safety-gate/         # 안전 게이트 규칙
  auto-diagnosis/      # 자동 진단 방법
```

<div class="mt-3 text-sm opacity-60">
에이전트 간 직접 통신 (SendMessage)<br/>
작업 의존성 관리 (TaskCreate)<br/>
팀 단위 조율과 품질 보장
</div>

</div>

</div>

<div class="mt-4 p-3 border-l-2 border-orange-400/60 text-sm opacity-70">
<strong>핵심 차이:</strong> 현재는 "사람이 스크립트로 파이프라인을 짜는" 구조.
Harness는 "AI가 AI 팀을 조율하는" 구조. <strong>사람은 팀 구성만 설계한다.</strong>
</div>

---
layout: default
---

# Harness가 가져올 변화

<div class="grid grid-cols-2 gap-8 mt-6">

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">GAINS</div>

<div class="space-y-4 text-sm">

<div>
<span class="text-emerald-400 font-mono text-xs">+</span>
<strong> 전문성 분리</strong>
<div class="text-xs opacity-60 ml-5">분석/구현/검증 에이전트가 각자 깊이 있게</div>
</div>

<div>
<span class="text-emerald-400 font-mono text-xs">+</span>
<strong> 재사용성</strong>
<div class="text-xs opacity-60 ml-5">한번 정의한 에이전트+스킬을 다른 프로젝트에도</div>
</div>

<div>
<span class="text-emerald-400 font-mono text-xs">+</span>
<strong> 병렬 실행</strong>
<div class="text-xs opacity-60 ml-5">독립적 작업은 동시에 처리, 처리 시간 단축</div>
</div>

<div>
<span class="text-emerald-400 font-mono text-xs">+</span>
<strong> 품질 보장</strong>
<div class="text-xs opacity-60 ml-5">QA 에이전트가 경계면을 교차 검증</div>
</div>

</div>

</div>

<div>

<div class="text-xs font-mono text-white/40 mb-3 tracking-widest">ARCHITECTURE PATTERNS</div>

<div class="space-y-3">

<div class="p-3 border border-white/10 rounded-lg">
<span class="font-bold text-cyan-400 text-sm">파이프라인</span>
<span class="text-xs opacity-60 ml-2">A &rarr; B &rarr; C (순차 의존)</span>
</div>

<div class="p-3 border border-white/10 rounded-lg">
<span class="font-bold text-emerald-400 text-sm">팬아웃/팬인</span>
<span class="text-xs opacity-60 ml-2">분석 3개 병렬 &rarr; 결과 통합</span>
</div>

<div class="p-3 border border-white/10 rounded-lg">
<span class="font-bold text-orange-400 text-sm">생성-검증</span>
<span class="text-xs opacity-60 ml-2">구현 &rarr; QA &rarr; 피드백 &rarr; 재구현</span>
</div>

<div class="p-3 border border-white/10 rounded-lg">
<span class="font-bold text-amber-400 text-sm">감독자</span>
<span class="text-xs opacity-60 ml-2">리더가 동적으로 작업 분배</span>
</div>

</div>

</div>

</div>

<div class="mt-4 p-3 border-l-2 border-emerald-400/60 text-sm opacity-70">
<strong>Lv3의 다음 단계:</strong> AI를 운영하는 시스템을 넘어, <strong>AI 팀을 설계하는 아키텍트</strong>가 된다.
</div>

---
layout: default
---

# KIS 프로젝트 장기 로드맵 &mdash; Phase별 Harness 적용

<div class="text-sm mt-1 opacity-60">
지금의 자율 운영 파이프라인 위에, 4단계로 점진적으로 Harness를 얹는다. 한 번에 다 바꾸지 않는다.
</div>

<div class="grid grid-cols-2 gap-3 mt-4">

<div class="p-4 border-l-2 border-cyan-400/60 bg-cyan-500/[0.03] rounded-r-lg">
<div class="text-xs font-mono text-cyan-400/70 mb-1 tracking-widest">PHASE 0 &mdash; 현재 (Lv3)</div>
<div class="font-bold text-sm mb-1">스크립트 파이프라인 + 파일 통신</div>
<div class="text-xs opacity-70 space-y-0.5">

- launchd × 6 + Claude Desktop 스케줄 × 3, proposals/reports 디렉토리
- BRIDGE_SPEC.md가 사실상의 "에이전트 헌법"
- 자동 구현 63건 / 5분/일 운영 비용

</div>
</div>

<div class="p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.03] rounded-r-lg">
<div class="text-xs font-mono text-emerald-400/70 mb-1 tracking-widest">PHASE 1 &mdash; 1~2개월</div>
<div class="font-bold text-sm mb-1">에이전트 분리 (선언화)</div>
<div class="text-xs opacity-70 space-y-0.5">

- BRIDGE_SPEC을 <code>.claude/agents/</code> 4개로 분해<br/>(market-analyst, code-implementer, qa-verifier, auto-healer)
- safety-gate를 <code>.claude/skills/</code>로 추출
- launchd는 그대로 유지 (변화 최소화)

</div>
<div class="text-[11px] opacity-50 mt-1 italic">▶ 이득: 새 에이전트(예: 보안 감사) 추가 비용이 "마크다운 한 장"으로</div>
</div>

<div class="p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.03] rounded-r-lg">
<div class="text-xs font-mono text-emerald-400/70 mb-1 tracking-widest">PHASE 2 &mdash; 3~4개월</div>
<div class="font-bold text-sm mb-1">팬아웃 분석 (병렬화)</div>
<div class="text-xs opacity-70 space-y-0.5">

- 16:00 분석을 3분할 병렬:<br/>(1) 거래 패턴, (2) 리스크/MDD, (3) 시그널 품질
- synthesizer 에이전트가 통합 → 단일 제안서
- 분석 깊이 ↑, 총 소요 시간 ↓

</div>
<div class="text-[11px] opacity-50 mt-1 italic">▶ 이득: 한 분석가가 못 보는 사각지대 → 다관점 교차 검증</div>
</div>

<div class="p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.03] rounded-r-lg">
<div class="text-xs font-mono text-emerald-400/70 mb-1 tracking-widest">PHASE 3 &mdash; 5~6개월</div>
<div class="font-bold text-sm mb-1">생성-검증 루프 (자가 개선)</div>
<div class="text-xs opacity-70 space-y-0.5">

- code-implementer ⇄ qa-verifier 자동 반복
- pytest 실패 → 원인 분석 → 재구현 (현재는 1회 실패면 끝)
- 매치율 90% 미만이면 iterator가 자동 재시도

</div>
<div class="text-[11px] opacity-50 mt-1 italic">▶ 이득: failed 비율 감소, 사람 개입 빈도 추가 감소</div>
</div>

<div class="p-4 border-l-2 border-amber-400/60 bg-amber-500/[0.03] rounded-r-lg col-span-2">
<div class="text-xs font-mono text-amber-400/70 mb-1 tracking-widest">PHASE 4 &mdash; 6개월+ (장기)</div>
<div class="font-bold text-sm mb-1">감독자 + 백테스트 통합 (자율 전략 진화)</div>
<div class="grid grid-cols-2 gap-4 text-xs opacity-70 mt-1">

<div class="space-y-0.5">

- supervisor 에이전트가 일일 상황 보고 후<br/>그날의 작업 구성을 동적으로 결정
- 새 전략 제안 → 자동 백테스트 → 통계적 유의미하면 가상계좌 카나리 → 실전 점진 적용
- watchdog/auto-heal이 supervisor에 통합

</div>

<div class="space-y-0.5">

- 안전장치는 더 보수적으로:<br/>실전계좌 자동 변경은 카나리 + 사람 승인 게이트 유지
- KIS_ENV: real에 대한 변경은 <strong>여전히 사람</strong>의 영역
- 메트릭/감사 로그를 supervisor가 정기 리뷰

</div>

</div>
<div class="text-[11px] opacity-50 mt-1 italic">▶ 이득: "AI를 운영하는 사람"에서 "AI 팀을 설계하는 아키텍트"로 완전 이행</div>
</div>

</div>

<div class="mt-3 p-2 border-l-2 border-orange-400/60 text-xs opacity-70">
<strong>로드맵 원칙:</strong> 각 Phase는 이전 Phase 위에 얹는다. 실패 시 즉시 이전 Phase로 롤백 가능하도록 분기 단위로 작업한다.
</div>

---
layout: default
---

# Phase 1 즉시 착수 가능 &mdash; 구체 작업 항목

<div class="text-sm mt-1 opacity-60">
다음 PDCA 사이클에서 바로 시작할 수 있는 가장 작은 첫걸음.
</div>

<div class="grid grid-cols-2 gap-5 mt-4">

<div>

```
.claude/
├── agents/
│   ├── market-analyst.md
│   │   ← scripts/cowork_*.py + BRIDGE_SPEC
│   │     의 "Cowork 역할" 부분 이전
│   ├── code-implementer.md
│   │   ← run_auto_implement.sh + 안전 게이트
│   │     검증 로직 이전
│   ├── qa-verifier.md
│   │   ← pytest/mypy/ruff 실행 +
│   │     실패 시 진단 책임 분리
│   └── auto-healer.md
│       ← scripts/auto_heal.sh의 판단 로직 이전
└── skills/
    ├── safety-gate/
    │   ← BRIDGE_SPEC.md의 25개 파라미터 표 +
    │     금지 영역 + 검증 스크립트
    ├── trading-analytics/
    │   ← scripts/query_analytics.py 호출 SOP
    └── log-diagnosis/
        ← logs/autotrader.log 패턴 분류 SOP
```

</div>

<div class="space-y-3 text-sm">

<div class="text-xs font-mono text-white/40 mb-2 tracking-widest">기대 효과 (Phase 1만으로도)</div>

<div class="p-3 border border-emerald-500/20 rounded-lg bg-emerald-500/[0.03]">
<div class="font-bold text-emerald-400 text-sm mb-1">① 새 역할 추가 비용 ↓</div>
<div class="text-xs opacity-70">"매월 의존성 보안 감사" 같은 신규 루틴 = security-auditor.md 한 장.</div>
</div>

<div class="p-3 border border-emerald-500/20 rounded-lg bg-emerald-500/[0.03]">
<div class="font-bold text-emerald-400 text-sm mb-1">② 모듈 경계 명시화</div>
<div class="text-xs opacity-70">CLAUDE.md "모듈 경계" 표가 에이전트 책임 표와 1:1 매핑되어 강제된다.</div>
</div>

<div class="p-3 border border-emerald-500/20 rounded-lg bg-emerald-500/[0.03]">
<div class="font-bold text-emerald-400 text-sm mb-1">③ 다른 프로젝트로 이식 가능</div>
<div class="text-xs opacity-70">safety-gate 스킬은 KIS 외 어떤 자동 구현 시스템에도 그대로 들어간다.</div>
</div>

<div class="p-3 border border-emerald-500/20 rounded-lg bg-emerald-500/[0.03]">
<div class="font-bold text-emerald-400 text-sm mb-1">④ 운영 OS 진입</div>
<div class="text-xs opacity-70">Phase 2~4에서 필요한 "에이전트라는 1차 구성요소"를 갖추게 된다.</div>
</div>

</div>

</div>

<div class="mt-3 p-2 border-l-2 border-emerald-400/60 text-xs opacity-70">
<strong>리스크:</strong> Phase 1은 <em>리팩토링</em>이지 신규 기능이 아니다. 기존 동작이 그대로 보존되는지 회귀 테스트가 핵심 게이트.
</div>

---
layout: section
---

# Part 5.

## 개발자의 새로운 역할

---
layout: default
---

# AI가 잘하는 것 / 사람이 잘해야 하는 것

<div class="grid grid-cols-2 gap-6 mt-6">

<div class="p-5 border border-cyan-500/20 rounded-xl bg-cyan-500/[0.03]">

<div class="text-xs font-mono text-cyan-400/70 mb-3 tracking-widest">AI EXCELS AT</div>

<div class="space-y-1.5 text-sm opacity-85">

- 알려진 패턴의 코드 작성
- 보일러플레이트, 테스트 케이스
- 문서 초안, 주석
- 로그/데이터 분석
- 리팩토링 제안
- API 스펙대로 구현
- 반복 작업 자동화

</div>

<div class="mt-4 text-xs opacity-40 italic">
"전에 본 적 있는 일"을 빠르게
</div>

</div>

<div class="p-5 border border-orange-500/20 rounded-xl bg-orange-500/[0.03]">

<div class="text-xs font-mono text-orange-400/70 mb-3 tracking-widest">HUMANS MUST OWN</div>

<div class="space-y-1.5 text-sm opacity-85">

- **문제 정의** ("뭘 풀어야 하는가")
- **시스템 설계** (구조와 경계)
- **트레이드오프 결정**
- **도메인 이해** (왜 그런 비즈니스인가)
- **안전성 판단** (뭐가 위험한가)
- **책임지기** (잘못됐을 때)
- **다른 사람과 협업**

</div>

<div class="mt-4 text-xs opacity-40 italic">
"전에 본 적 없는 일"을 정확히
</div>

</div>

</div>

---
layout: center
class: text-center
---

<div class="text-xl opacity-40 mb-10 tracking-wider">지난 한 달</div>

<div class="grid grid-cols-3 gap-8 max-w-3xl mx-auto">

<div class="text-center">
<div class="text-6xl font-bold text-orange-400">0</div>
<div class="text-sm opacity-60 mt-2">내가 직접 작성한 코드</div>
</div>

<div class="text-center">
<div class="text-6xl font-bold text-cyan-400">5분</div>
<div class="text-sm opacity-60 mt-2">하루에 CHANGELOG 읽는 시간</div>
</div>

<div class="text-center">
<div class="text-6xl font-bold text-emerald-400">63건</div>
<div class="text-sm opacity-60 mt-2">자동 구현된 변경</div>
</div>

</div>

<div class="mt-8 text-center">
<span class="font-mono text-2xl text-white/70">+19,806</span>
<span class="text-sm opacity-40 mx-2">/</span>
<span class="font-mono text-2xl text-white/70">-740</span>
<span class="text-sm opacity-40 ml-3">lines changed (src + tests)</span>
</div>

<div class="mt-12 text-base opacity-50 max-w-xl mx-auto leading-relaxed">
같은 양의 코드를 직접 조사하고, 공부하고, 작성하려면<br/>
<strong class="text-white/80">하루 5시간도 모자랐을 것이다.</strong>
</div>

<div class="mt-6 text-sm opacity-30">
그 5시간을 시스템 설계와 의사결정에 쓴다.
</div>

---
layout: default
---

# 내일부터 할 수 있는 것

<div class="space-y-4 mt-6">

<div class="flex items-start gap-4 p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.02] rounded-r-lg">
<div class="font-mono text-emerald-400 text-xs w-20 shrink-0 pt-0.5">DAY 1</div>
<div>
<div class="font-bold text-sm">CLAUDE.md를 만들어라</div>
<div class="text-xs opacity-60 mt-1">현재 프로젝트의 README와 별개로, AI 전용 컨텍스트 파일. 한 페이지로 시작.</div>
</div>
</div>

<div class="flex items-start gap-4 p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.02] rounded-r-lg">
<div class="font-mono text-emerald-400 text-xs w-20 shrink-0 pt-0.5">WEEK 1</div>
<div>
<div class="font-bold text-sm">반복 분석 작업 하나를 자동화하라</div>
<div class="text-xs opacity-60 mt-1">매주 하던 리포트, 매일 보던 메트릭. AI + 스케줄러로.</div>
</div>
</div>

<div class="flex items-start gap-4 p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.02] rounded-r-lg">
<div class="font-mono text-emerald-400 text-xs w-20 shrink-0 pt-0.5">MONTH 1</div>
<div>
<div class="font-bold text-sm">분석/구현 분리 파이프라인을 만들어라</div>
<div class="text-xs opacity-60 mt-1">규모는 작아도 좋다. "AI가 제안하고 검증된 변경만 적용된다" 구조의 첫 시도.</div>
</div>
</div>

<div class="flex items-start gap-4 p-4 border-l-2 border-emerald-400/60 bg-emerald-500/[0.02] rounded-r-lg">
<div class="font-mono text-emerald-400 text-xs w-20 shrink-0 pt-0.5">QUARTER</div>
<div>
<div class="font-bold text-sm">팀에 도입을 제안하라</div>
<div class="text-xs opacity-60 mt-1">개인 워크플로우를 팀 워크플로우로. 이 발표가 그 출발점이 되길.</div>
</div>
</div>

</div>

---
layout: center
class: text-center
---

<div class="text-xl opacity-40 mb-10 font-serif italic">
처음에 물었습니다 &mdash; 사용하는가, 운영하는가.
</div>

<div class="text-4xl font-bold leading-relaxed">

여러분의 <span class="text-orange-400">오후 4시</span>에는

<div class="mt-6">
무엇이 일어나고 있나요?
</div>

</div>

<div class="mt-16 text-base opacity-40">
아무 일도 일어나지 않는다면, 오늘이 시작점입니다.
</div>

---
layout: end
class: text-center
---

# 감사합니다

<div class="mt-8 text-lg opacity-60">
질문 / 토론
</div>

<div class="mt-12 font-mono text-sm opacity-40">
한수 &middot; 주식회사 퍼닌
</div>
