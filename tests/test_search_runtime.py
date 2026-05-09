import hashlib
import json

import numpy as np

from search_runtime import PaperSearcher, _dataset_fingerprints, describe_cache_status, get_cache_paths


class DummySearcher(PaperSearcher):
    embed_history = []

    def _init_model(self):
        return object()

    def _embed(self, texts, stage_message="Embedding papers"):
        self.embed_history.append(list(texts))
        return np.array([[float(len(text))] for text in texts], dtype=np.float32)


def write_db(path, papers):
    path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")


def test_search_runtime_reorders_cache_when_order_changes(tmp_path):
    db_file = tmp_path / "papers.json"
    papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Beta"},
    ]
    write_db(db_file, papers)

    DummySearcher.embed_history = []
    DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    assert len(DummySearcher.embed_history) == 1
    assert len(DummySearcher.embed_history[0]) == 2

    write_db(db_file, list(reversed(papers)))
    status = describe_cache_status(str(db_file), "all-MiniLM-L6-v2")
    assert status["cached_papers"] == 2
    assert status["new_papers"] == 0
    searcher = DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
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
    DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    assert len(DummySearcher.embed_history[0]) == 2

    changed_papers = [
        {"title": "Paper A", "abstract": "Alpha"},
        {"title": "Paper B", "abstract": "Gamma"},
    ]
    write_db(db_file, changed_papers)
    status = describe_cache_status(str(db_file), "all-MiniLM-L6-v2")
    assert status["cached_papers"] == 1
    assert status["new_papers"] == 1

    searcher = DummySearcher(str(db_file), model_name="voyage-4-large")
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
