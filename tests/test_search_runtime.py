import json

import numpy as np

from search_runtime import PaperSearcher


class DummySearcher(PaperSearcher):
    embed_history = []

    def _init_model(self):
        return object()

    def _embed(self, texts):
        self.embed_history.append(list(texts))
        return np.array([[float(len(text))] for text in texts], dtype=np.float32)


def write_db(path, papers):
    path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")


def test_search_runtime_rebuilds_cache_when_order_changes(tmp_path):
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
    DummySearcher(str(db_file), model_name="all-MiniLM-L6-v2")
    assert len(DummySearcher.embed_history[-1]) == 2

