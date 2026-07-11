import importlib.util
import io
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "chipseeker_agent_search.py"
SPEC = importlib.util.spec_from_file_location("chipseeker_agent_search_cli", SCRIPT_PATH)
AGENT_CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT_CLI)


class BinaryStdout:
    def __init__(self):
        self.buffer = io.BytesIO()


def test_agent_cli_writes_matching_utf8_stdout_and_output_file(monkeypatch, tmp_path):
    stdout = BinaryStdout()
    monkeypatch.setattr(AGENT_CLI.sys, "stdout", stdout)
    output_path = tmp_path / "queries" / "round_001.json"
    payload = {"schema": "chipseeker-agent-search/v1", "query": "低温量子LNA"}

    AGENT_CLI.write_json(payload, output_path)

    stdout_payload = stdout.buffer.getvalue()
    assert stdout_payload == output_path.read_bytes()
    assert json.loads(stdout_payload.decode("utf-8")) == payload
