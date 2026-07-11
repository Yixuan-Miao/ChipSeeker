from datetime import datetime

from chipseeker.ultra_workspace import WORKSPACE_FILES, create_workspace, safe_direction_name, workspace_status


def test_workspace_keeps_direction_and_creates_research_assets(tmp_path):
    workspace = create_workspace(
        "SiGe 130nm transmon readout LNA",
        tmp_path,
        created_at=datetime(2026, 7, 11, 10, 30, 45),
    )

    assert workspace.name == "20260711_103045_SiGe_130nm_transmon_readout_LNA"
    assert (workspace / "queries").is_dir()
    assert all((workspace / filename).is_file() for filename in WORKSPACE_FILES)
    assert "Original Direction" in (workspace / "00_PROJECT_BRIEF.md").read_text(encoding="utf-8")


def test_workspace_status_and_unicode_direction(tmp_path):
    assert safe_direction_name("低温 / 量子: LNA") == "低温_量子_LNA"
    workspace = create_workspace("低温量子LNA", tmp_path, created_at=datetime(2026, 7, 11, 10, 30, 45))
    status = workspace_status(workspace)
    assert status["exists"] is True
    assert all(status["required_files"].values())
