import hashlib
import json
import time

import numpy as np
import pytest

from search_runtime import PaperSearcher, _dataset_fingerprints, _semantic_search, describe_cache_status, get_cache_paths


class DummySearcher(PaperSearcher):
    embed_history = []

    def _init_model(self):
        return object()

    def _embed(self, texts, stage_message="Embedding papers"):
        self.embed_history.append(list(texts))
        return np.array([[float(len(text))] for text in texts], dtype=np.float32)


class SlowRemoteQuerySearcher(DummySearcher):
    def _embed(self, texts, stage_message="Embedding papers", **_kwargs):
        self.embed_history.append(list(texts))
        if stage_message.startswith("Embedding quer"):
            time.sleep(0.06)
        return np.array([[float(len(text))] for text in texts], dtype=np.float32)


class StreamingRemoteSearcher(PaperSearcher):
    def _remote_embed_batch(
        self,
        batch,
        batch_index,
        total_batches,
        stage_message,
        start_idx,
        total,
        max_attempts=3,
    ):
        return [[float(len(text)), float(start_idx + offset)] for offset, text in enumerate(batch)]


def write_db(path, papers):
    path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")


def test_semantic_search_chunking_matches_full_matrix_ranking(monkeypatch):
    corpus = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.8, 0.2, 0.0],
            [0.0, 1.0, 0.0],
            [0.2, 0.8, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    query = np.array([1.0, 0.25, 0.0], dtype=np.float32)
    expected_scores = (corpus @ query) / (np.linalg.norm(corpus, axis=1) * np.linalg.norm(query))
    expected_indexes = np.argsort(-expected_scores)[:4]

    monkeypatch.setenv("CHIPSEEKER_SEARCH_CHUNK_SIZE", "2")
    results = _semantic_search(query, corpus, top_k=4)

    assert [item["corpus_id"] for item in results] == expected_indexes.tolist()
    assert np.allclose(
        [item["score"] for item in results],
        expected_scores[expected_indexes],
    )


def test_exact_cache_is_loaded_as_read_only_memmap(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIPSEEKER_MMAP_EMBEDDINGS", "1")
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, papers)

    DummySearcher.embed_history = []
    first_searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    first_searcher._ensure_embeddings()
    second_searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    second_searcher._ensure_embeddings()

    assert isinstance(second_searcher.eb, np.memmap)
    assert second_searcher.eb.mode == "r"


def test_remote_embeddings_are_written_into_one_float32_matrix(tmp_path):
    db_file = tmp_path / "papers.json"
    write_db(db_file, [{"title": "unused"}])
    searcher = StreamingRemoteSearcher(
        str(db_file),
        model_name="voyage-4-large",
        api_key="unused",
    )

    embeddings = searcher._embed(
        ["a", "bb", "ccc", "dddd", "eeeee"],
        batch_size_override=2,
    )

    assert embeddings.dtype == np.float32
    assert embeddings.shape == (5, 2)
    assert np.array_equal(
        embeddings,
        np.array(
            [
                [1.0, 0.0],
                [2.0, 1.0],
                [3.0, 2.0],
                [4.0, 3.0],
                [5.0, 4.0],
            ],
            dtype=np.float32,
        ),
    )


def test_request_safe_searcher_rejects_large_partial_cache_repair(tmp_path):
    db_file = tmp_path / "papers.json"
    initial_papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, initial_papers)
    DummySearcher.embed_history = []
    builder = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    builder._ensure_embeddings()
    del builder

    changed_papers = [
        {"title": "Paper A", "abstract": "Changed"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, changed_papers)
    searcher = DummySearcher(
        str(db_file),
        model_name="all-MiniLM-L6-v2",
        cache_repair_limit=0,
    )

    with pytest.raises(RuntimeError, match="requires offline maintenance"):
        searcher._ensure_embeddings()

    assert len(DummySearcher.embed_history) == 1


def test_search_runtime_reorders_cache_when_order_changes(tmp_path):
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, papers)

    DummySearcher.embed_history = []
    first_searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    first_searcher._ensure_embeddings()
    assert len(DummySearcher.embed_history) == 1
    assert len(DummySearcher.embed_history[0]) == 2

    write_db(db_file, list(reversed(papers)))
    status = describe_cache_status(str(db_file), "all-MiniLM-L6-v2")
    assert status["cached_papers"] == 2
    assert status["new_papers"] == 0
    searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    searcher._ensure_embeddings()
    assert len(DummySearcher.embed_history) == 1
    assert np.array_equal(searcher.eb, np.array([[12.0], [13.0]], dtype=np.float32))


def test_search_runtime_repairs_only_changed_fingerprints(tmp_path):
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, papers)

    DummySearcher.embed_history = []
    first_searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    first_searcher._ensure_embeddings()
    assert len(DummySearcher.embed_history[0]) == 2

    changed_papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Gamma"},
    ]
    write_db(db_file, changed_papers)
    status = describe_cache_status(str(db_file), "all-MiniLM-L6-v2")
    assert status["cached_papers"] == 1
    assert status["new_papers"] == 1

    searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    searcher._ensure_embeddings()
    assert DummySearcher.embed_history[-1] == ["Paper B Gamma"]
    assert np.array_equal(searcher.eb, np.array([[13.0], [13.0]], dtype=np.float32))


def test_search_runtime_reuses_legacy_hash_cache_after_database_move(tmp_path):
    source_db = tmp_path / "seller" / "isscc_papers.json"
    target_db = tmp_path / "buyer" / "isscc_papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    source_db.parent.mkdir()
    target_db.parent.mkdir()
    write_db(source_db, papers)
    write_db(target_db, papers)

    cache_dir = target_db.parent / "cache"
    cache_dir.mkdir()
    source_hash = hashlib.sha1(str(source_db.resolve()).encode("utf-8")).hexdigest()[:8]
    legacy_cache = cache_dir / f"cache_isscc_papers_{source_hash}_all-MiniLM-L6-v2_all.npy"
    legacy_meta = cache_dir / f"cache_isscc_papers_{source_hash}_all-MiniLM-L6-v2_all.meta.json"
    embeddings = np.array([[1.0], [2.0]], dtype=np.float32)
    np.save(legacy_cache, embeddings)
    legacy_meta.write_text(
        json.dumps(
            {
                "db_file": str(source_db.resolve()),
                "model_name": "all-MiniLM-L6-v2",
                "fingerprints": _dataset_fingerprints(papers),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    DummySearcher.embed_history = []
    status = describe_cache_status(str(target_db), "all-MiniLM-L6-v2")
    assert status["up_to_date"] is True
    assert status["needs_build"] is False

    searcher = DummySearcher(str(target_db), model_name="all-MiniLM-L6-v2")
    searcher._ensure_embeddings()
    assert DummySearcher.embed_history == []
    assert np.array_equal(searcher.eb, embeddings)

    portable_cache, portable_meta = get_cache_paths(str(target_db), "all-MiniLM-L6-v2")
    assert portable_cache.endswith("cache_isscc_papers_all-MiniLM-L6-v2_all.npy")
    assert portable_meta.endswith("cache_isscc_papers_all-MiniLM-L6-v2_all.meta.json")
    assert (cache_dir / "cache_isscc_papers_all-MiniLM-L6-v2_all.npy").exists()
    assert (cache_dir / "cache_isscc_papers_all-MiniLM-L6-v2_all.meta.json").exists()


def test_search_candidates_reranks_exact_filtered_subset(tmp_path):
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Much longer beta text"},
        {"title": "Paper C", "abstract": "Gamma"},
    ]
    write_db(db_file, papers)

    DummySearcher.embed_history = []
    searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    results = searcher.search_candidates(
        "query",
        [papers[2], papers[0]],
        top_k=10,
    )

    assert len(results) == 2
    assert {item["paper"]["title"] for item in results} == {"Paper A", "Paper C"}


def test_search_many_embeds_all_queries_in_one_batch(tmp_path):
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, papers)

    DummySearcher.embed_history = []
    searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    searcher._ensure_embeddings()
    DummySearcher.embed_history = []
    results = searcher.search_many(["short", "longer query"], top_k=1)

    assert len(results) == 2
    assert DummySearcher.embed_history == [["short", "longer query"]]


def test_remote_search_many_embeds_queries_concurrently(tmp_path):
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, papers)

    SlowRemoteQuerySearcher.embed_history = []
    searcher = SlowRemoteQuerySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    searcher._ensure_embeddings()
    searcher.mt = "v"
    searcher.md = object()
    SlowRemoteQuerySearcher.embed_history = []
    started = time.perf_counter()
    results = searcher.search_many(["one", "two", "three"], top_k=1, query_workers=3)
    elapsed = time.perf_counter() - started

    assert len(results) == 3
    assert sorted(SlowRemoteQuerySearcher.embed_history) == [["one"], ["three"], ["two"]]
    assert elapsed < 0.14
