#!/usr/bin/env bash
# 실전(real) 전환 전 1회 실행 — kis_trader_real 스키마 부트스트랩.
#
# 검토(2026-05-30) 블로커: kis_trader_real DB에 테이블이 0개이며 alembic_version도
# 없다. 앱 부팅 시 Base.metadata.create_all로 테이블 자체는 생기지만 마이그레이션
# 추적(alembic_version)이 없어 이후 스키마 변경이 꼬인다. 이 스크립트는 실전 첫
# 기동 전에 `alembic upgrade head`로 전체 스키마 + 마이그레이션 이력을 정식 적재한다.
#
# 안전: KIS_ENV=real을 강제하면 settings.db.url이 DATABASE_URL_REAL(=kis_trader_real)로
# 해석되어, 운영 중인 모의(kis_trader) DB는 건드리지 않는다. 멱등(idempotent).
#
# 사용: scripts/bootstrap_real_db.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✗ .env 파일이 없습니다. DATABASE_URL_REAL 설정 후 다시 실행하세요." >&2
  exit 1
fi

# 프로젝트 venv 우선(시스템에 'python' 심볼릭이 없을 수 있음 — python3만 존재).
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "✗ python 실행 파일을 찾을 수 없습니다 (.venv/bin/python 또는 python3)." >&2
  exit 1
fi

# .env는 load_dotenv(override=False)로 로드되므로 여기서 export한 KIS_ENV가 우선한다.
export KIS_ENV=real

echo "▶ 사용 파이썬: $PYTHON"
echo "▶ 대상 DB (real):"
"$PYTHON" - <<'PY'
from src.config import settings
url = settings.db.url
# 비밀번호 마스킹 후 출력
import re
print("   " + re.sub(r"//([^:]+):[^@]+@", r"//\1:***@", url))
assert settings.kis.env == "real", "KIS_ENV=real 강제 실패"
PY

echo "▶ 현재 마이그레이션 상태:"
"$PYTHON" -m alembic current || true

echo "▶ alembic upgrade head 실행..."
"$PYTHON" -m alembic upgrade head

echo "▶ 적재 결과 (kis_trader_real 테이블 수):"
docker exec kis-postgres psql -U kis_user -d kis_trader_real -tc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" \
  || echo "   (docker psql 확인 생략 — 컨테이너명/권한 확인 필요)"

echo "✓ 완료. 이제 KIS_ENV=real 기동 시 정식 스키마가 준비됩니다."
