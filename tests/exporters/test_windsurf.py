from datetime import datetime
from pathlib import Path

from anyspecs.exporters.windsurf import WindsurfExtractor


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "windsurf" / "storage"


def make_extractor(app_root: Path, storage_root: Path, cwd: Path, monkeypatch) -> WindsurfExtractor:
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    extractor = WindsurfExtractor()
    extractor.app_root = app_root
    extractor.storage_root = storage_root
    return extractor


def test_extracts_windsurf_fixture_with_project_mapping_and_messages(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-learning-platform"
    extractor = make_extractor(
        FIXTURE_ROOT / "app",
        FIXTURE_ROOT / "codeium",
        project_dir,
        monkeypatch,
    )

    chats = extractor.extract_chats()

    assert len(chats) == 1
    chat = chats[0]
    assert chat["session_id"] == "cbc99144-4e48-4e68-89f7-3f1608611bbe"
    assert chat["workspace_id"] == "359c582b8bf0e42edf8be0b6be435fa6"
    assert chat["project"]["name"] == "demo-learning-platform"
    assert chat["project"]["rootPath"] == "/Users/redacted/work/sample/code/demo-learning-platform"
    assert chat["session"]["title"] == "Project Overview"
    assert chat["session"]["createdAt"] == 1774347887599
    assert chat["session"]["lastUpdatedAt"] == 1774347896931
    assert chat["metadata"]["storage_kind"] == "windsurf_cache"
    assert chat["metadata"]["workspace_id"] == "359c582b8bf0e42edf8be0b6be435fa6"
    assert len(chat["messages"]) == 3
    assert [message["role"] for message in chat["messages"]] == [
        "user",
        "assistant",
        "assistant",
    ]
    assert chat["messages"][0]["content"] == "介绍下项目概况"
    assert "analyze the project structure" in chat["messages"][1]["content"]
    assert "# 项目概况" in chat["messages"][2]["content"]


def test_list_sessions_filters_current_project_and_formats_preview(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-learning-platform"
    extractor = make_extractor(
        FIXTURE_ROOT / "app",
        FIXTURE_ROOT / "codeium",
        project_dir,
        monkeypatch,
    )

    sessions = extractor.list_sessions()

    assert len(sessions) == 1
    expected_date = datetime.fromtimestamp(1774347887599 / 1000).strftime(
        "%Y-%m-%d %H:%M"
    )
    assert sessions[0]["session_id"] == "cbc99144"
    assert sessions[0]["project"] == "demo-learning-platform"
    assert sessions[0]["date"] == expected_date
    assert sessions[0]["message_count"] == 3
    assert sessions[0]["preview"] == "介绍下项目概况"
    assert sessions[0]["workspace_id"] == "359c582b8bf0e42edf8be0b6be435fa6"
