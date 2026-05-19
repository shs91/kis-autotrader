"""Aho-Corasick 기반 종목 매칭.

뉴스/공시 본문에서 종목명을 다중 매칭하여 종목코드 리스트를 반환한다.
정규식 OR 누적은 종목 수 1,000+에서 비효율이라 automaton 접근.

False positive 차단:
- 종목명 길이 < `min_name_length`(기본 3)면 무시 — "삼성", "한화" 등
  단독 토큰은 동음이의 위험.
- 한 위치에서 여러 종목명이 매칭되면 가장 긴 매칭만 채택 — "삼성바이오로직스"
  매칭 시 "삼성전자"는 제외.
- 중복 종목코드는 dedup.
"""

from __future__ import annotations

import ahocorasick  # type: ignore[import-not-found]

DEFAULT_MIN_NAME_LENGTH = 3


class TickerMatcher:
    """종목명 → 종목코드 다중 매칭."""

    def __init__(
        self,
        stocks: list[tuple[str, str]],
        min_name_length: int = DEFAULT_MIN_NAME_LENGTH,
    ) -> None:
        """
        Args:
            stocks: (code, name) 쌍 리스트.
            min_name_length: 이 미만 길이의 종목명은 매칭 대상에서 제외.
        """
        self._min_name_length = min_name_length
        self._automaton = ahocorasick.Automaton()
        for code, name in stocks:
            if len(name) < min_name_length:
                continue
            # (code, name) 페이로드로 가장 긴 매칭 판정에 사용
            self._automaton.add_word(name, (code, name))
        # 종목이 0개일 때도 make_automaton 호출은 안전
        if len(self._automaton) > 0:
            self._automaton.make_automaton()

    def match(self, text: str) -> list[str]:
        """본문에서 매칭된 종목코드 리스트(중복 제거, 발견 순서 보존)."""
        if not text or len(self._automaton) == 0:
            return []

        # 매칭 결과 수집: end_idx → (start_idx, code, name_len)
        # 같은 위치 또는 겹치는 위치에서는 가장 긴 매칭만 채택.
        matches: list[tuple[int, int, str, int]] = []
        for end_idx, (code, name) in self._automaton.iter(text):
            start_idx = end_idx - len(name) + 1
            matches.append((start_idx, end_idx, code, len(name)))

        # 정렬: start asc, length desc (긴 매칭 우선)
        matches.sort(key=lambda m: (m[0], -m[3]))

        # 겹치는 매칭 제거: 직전에 채택한 매칭의 end보다 start가 크거나 같을 때만 새로 채택
        accepted_codes: list[str] = []
        seen: set[str] = set()
        last_end = -1
        for start, end, code, _ in matches:
            if start <= last_end:
                continue
            last_end = end
            if code not in seen:
                accepted_codes.append(code)
                seen.add(code)
        return accepted_codes
