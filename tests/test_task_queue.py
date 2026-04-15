import time

from chipseeker import task_queue


class DummySearcher:
    def __init__(self, db_file, model_name, api_key=""):
        self.db_file = db_file
        self.model_name = model_name
        self.api_key = api_key


def test_embedding_task_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(task_queue, "PaperSearcher", DummySearcher)
    task_id = task_queue.submit_embedding_build(str(tmp_path / "papers.json"), "all-MiniLM-L6-v2")

    deadline = time.time() + 5
    task = task_queue.get_task(task_id)
    while task and task["status"] not in {"completed", "failed"} and time.time() < deadline:
        time.sleep(0.05)
        task = task_queue.get_task(task_id)

    assert task is not None
    assert task["status"] == "completed"
    assert task["result"]["model_name"] == "all-MiniLM-L6-v2"
