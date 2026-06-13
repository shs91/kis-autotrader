"""pytest 전역 설정 — 운영(real) .env가 테스트에 누수되지 않도록 격리.

이 모듈은 pytest가 테스트 수집 전에 가장 먼저 import한다. 따라서 여기서
os.environ을 정리하면, 이후 어떤 테스트 모듈이 src.config를 import해도
settings = Settings()가 virtual + 코드 기본값 기준으로 로드된다.

배경: KIS_ENV=real 운영 환경에서 pytest를 돌리면 config가 DATABASE_URL_REAL/
실전 TR ID/운영 전략 튜닝값을 읽어, 환경 의존 테스트 8건이 깨졌다
(2026-06-13 확정). 자세한 내용은 docs/proposals/2026-06-13_test-env-isolation.md.

[보정 메모] 제안서 초안은 STRATEGY_*/SCREENING_* 키를 os.environ에서 pop(삭제)
하면 코드 기본값을 쓴다고 가정했으나, 이는 **무효**다. src/config.py의
load_dotenv(override=False)가 부재 키를 .env에서 **다시 주입**하고, settings는
import 시점 1회 빌드 싱글톤이라 .env의 STRATEGY_RSI_PERIOD=9가 그대로 박힌다.
따라서 pop 대신 STRATEGY_RSI_PERIOD를 코드 기본값 "14"로 **SET**한다.
load_dotenv(override=False)는 이미 셋된 값을 존중하므로 싱글톤이 14를 읽어
RSIStrategy() → RSI(14) → test_rsi가 통과한다.
"""

from __future__ import annotations

import os

# 축 1 — 환경/DB 고정: config.py가 KIS_ENV=real이면 DATABASE_URL_REAL·실전
# TR ID를 쓰므로, 테스트는 항상 virtual로 고정해 모의 TR ID·테스트 DB를 쓴다.
os.environ["KIS_ENV"] = "virtual"
# KIS_ENV=virtual이면 config는 DATABASE_URL을 쓰므로 DATABASE_URL_REAL은
# 무시되나, 명시적으로 제거해 누수 의도를 차단한다(무해).
os.environ.pop("DATABASE_URL_REAL", None)

# 축 2 — 전략 튜닝값 차단: pop은 load_dotenv(override=False)+settings 싱글톤에
# 의해 무효(부재 키가 .env에서 재주입됨)이므로, RSI_PERIOD를 코드 기본값으로
# SET해 보정한다. .env의 STRATEGY_RSI_PERIOD=9 대신 14가 싱글톤에 박힌다.
os.environ["STRATEGY_RSI_PERIOD"] = "14"
