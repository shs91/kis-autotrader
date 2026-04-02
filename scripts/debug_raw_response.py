"""시세 API RAW 응답 확인."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.client import KISClient
from src.config import settings


async def main() -> None:
    print(f"환경: {settings.kis.env}")
    print(f"BASE URL: {settings.kis.base_url}")

    client = KISClient()

    # 현재가 조회
    print("\n=== 현재가 RAW 응답 (005930) ===")
    resp = await client.get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
        tr_id="FHKST01010100",
    )
    output = resp.get("output", {})
    print(f"rt_cd: {resp.get('rt_cd')}")
    print(f"STCK_PRPR (현재가): '{output.get('STCK_PRPR', 'MISSING')}'")
    print(f"HTS_KOR_ISNM (종목명): '{output.get('HTS_KOR_ISNM', 'MISSING')}'")
    print(f"output 키 일부: {list(output.keys())[:10]}")

    # 소문자 키 확인
    lower_keys = [k for k in output if k.islower()]
    upper_keys = [k for k in output if k.isupper()]
    print(f"대문자 키: {len(upper_keys)}개, 소문자 키: {len(lower_keys)}개")
    if lower_keys:
        print(f"소문자 키 예시: {lower_keys[:5]}")
        # 소문자로 현재가 확인
        print(f"stck_prpr: '{output.get('stck_prpr', 'MISSING')}'")

    # 일봉 조회
    print("\n=== 일봉 RAW 응답 (005930) ===")
    resp2 = await client.get(
        "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": "005930",
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        },
        tr_id="FHKST01010400",
    )
    output2 = resp2.get("output", [])
    print(f"rt_cd: {resp2.get('rt_cd')}")
    print(f"output 건수: {len(output2)}")
    if output2:
        first = output2[0]
        print(f"첫 번째 데이터: {json.dumps(first, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    asyncio.run(main())
