"""Embedder: dimension enforcement and instruction-prefix handling.

Uses a fake SentenceTransformer so no model is downloaded and no network is hit.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from src.errors import EmbeddingDimensionMismatch
from src.ingest.embedder import Embedder
from tests.conftest import make_settings


def _install_fake_sentence_transformers(monkeypatch, dim, sink):
    class FakeST:
        def __init__(self, name, *a, **k):
            self.name = name

        def get_sentence_embedding_dimension(self):
            return dim

        def encode(self, texts, **kwargs):
            single = isinstance(texts, str)
            items = [texts] if single else list(texts)
            sink.extend(items)
            arr = np.ones((len(items), dim), dtype=np.float32)
            return arr[0] if single else arr

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_encode_dimensions_and_prefixes(monkeypatch):
    sink: list[str] = []
    _install_fake_sentence_transformers(monkeypatch, dim=8, sink=sink)
    emb = Embedder(make_settings(embedding_dim=8))

    q = emb.encode_query("what PPE is required?")
    p = emb.encode_passages(["helmet and gloves", "grounding checks"])

    assert q.shape == (8,)
    assert p.shape == (2, 8)
    # e5-style instruction prefixes are applied to the text sent to the model.
    assert sink[0] == "query: what PPE is required?"
    assert "passage: helmet and gloves" in sink


def test_dimension_mismatch_raises(monkeypatch):
    sink: list[str] = []
    _install_fake_sentence_transformers(monkeypatch, dim=384, sink=sink)
    emb = Embedder(make_settings(embedding_dim=768))  # config says 768, model gives 384
    with pytest.raises(EmbeddingDimensionMismatch):
        emb.encode_query("hello")


def test_empty_passages_returns_empty_matrix(monkeypatch):
    sink: list[str] = []
    _install_fake_sentence_transformers(monkeypatch, dim=8, sink=sink)
    emb = Embedder(make_settings(embedding_dim=8))
    assert emb.encode_passages([]).shape == (0, 8)
