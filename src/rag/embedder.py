"""BGE-M3 임베딩 래퍼.

프로세스당 1회 모델 로드를 보장하는 싱글톤. Worker 프로세스에서만 인스턴스를
생성하며, 매매 메인 프로세스는 import만 하고 `Embedder.get()` 호출 금지.

첫 호출 시 ~5초 워밍업이 발생하므로 헬스체크에서는 별도 ready 플래그로 격리한다.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np

from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

logger = setup_logger(__name__)

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_BATCH_SIZE = 12
EMBEDDING_DIM = 1024


class Embedder:
    """BGE-M3 dense 임베딩 싱글톤.

    BGE-M3는 dense + sparse + multi-vector 출력을 모두 지원하지만 본 클래스는
    1024-dim dense 벡터만 노출한다. 하이브리드 검색은 후속 retriever에서 도입.
    """

    _instance: Embedder | None = None

    def __init__(self) -> None:
        # 무거운 import (torch 등). 싱글톤 초기화 시점까지 지연.
        from FlagEmbedding import BGEM3FlagModel

        model_name = os.getenv("NEWS_EMBEDDING_MODEL", DEFAULT_MODEL)
        logger.info("BGE-M3 모델 로드 시작: %s", model_name)
        self._model: BGEM3FlagModel = BGEM3FlagModel(model_name, use_fp16=True)
        logger.info("BGE-M3 모델 로드 완료")

    @classmethod
    def get(cls) -> Embedder:
        """싱글톤 인스턴스를 반환. 첫 호출 시 모델 로드(~5초)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def encode(
        self,
        texts: list[str],
        batch_size: int | None = None,
    ) -> np.ndarray:
        """텍스트 배치를 1024-dim dense 벡터로 인코딩한다.

        Args:
            texts: 인코딩할 텍스트 리스트.
            batch_size: 배치 크기. None이면 환경변수 또는 기본값 사용.

        Returns:
            shape=(len(texts), 1024)의 float ndarray. 빈 입력은 (0, 1024).
        """
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        bs = batch_size or int(
            os.getenv("NEWS_EMBEDDING_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
        )
        result = self._model.encode(texts, batch_size=bs)
        dense: np.ndarray = result["dense_vecs"]
        return dense
