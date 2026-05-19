"""Embedder (BGE-M3 래퍼) 단위 테스트.

실제 BGE-M3 로드는 무거우므로(~5초 + 2GB) FlagEmbedding을 mock한다.
실제 모델 검증은 별도 통합 테스트에서.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.rag.embedder import Embedder


@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    """각 테스트 시작 시 싱글톤 인스턴스를 초기화."""
    Embedder._instance = None


def _mock_model(dense_shape: tuple[int, int] = (1, 1024)) -> MagicMock:
    model = MagicMock()
    model.encode.return_value = {
        "dense_vecs": np.zeros(dense_shape, dtype=np.float32),
    }
    return model


class TestSingleton:
    @patch("FlagEmbedding.BGEM3FlagModel")
    def test_get_returns_same_instance(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = _mock_model()
        a = Embedder.get()
        b = Embedder.get()
        assert a is b

    @patch("FlagEmbedding.BGEM3FlagModel")
    def test_model_loaded_only_once(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = _mock_model()
        Embedder.get()
        Embedder.get()
        Embedder.get()
        # FlagEmbedding 모델 생성자는 정확히 1회만 호출된다.
        assert mock_cls.call_count == 1


class TestEncode:
    @patch("FlagEmbedding.BGEM3FlagModel")
    def test_encode_returns_dense_vectors(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = _mock_model(dense_shape=(2, 1024))
        embedder = Embedder.get()
        out = embedder.encode(["a", "b"])
        assert isinstance(out, np.ndarray)
        assert out.shape == (2, 1024)

    @patch("FlagEmbedding.BGEM3FlagModel")
    def test_encode_empty_list_returns_zero_rows(self, mock_cls: MagicMock) -> None:
        """빈 입력은 모델 호출 없이 (0, 1024) 반환 — 비용 절감."""
        mock_cls.return_value = _mock_model()
        embedder = Embedder.get()
        out = embedder.encode([])
        assert out.shape == (0, 1024)
        # 빈 입력에서는 모델 encode가 호출되지 않아야 한다.
        embedder._model.encode.assert_not_called()  # type: ignore[attr-defined]

    @patch("FlagEmbedding.BGEM3FlagModel")
    def test_encode_passes_batch_size(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = _mock_model(dense_shape=(3, 1024))
        embedder = Embedder.get()
        embedder.encode(["a", "b", "c"], batch_size=5)
        call_kwargs = embedder._model.encode.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs.get("batch_size") == 5
