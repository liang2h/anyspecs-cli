import logging
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from anyspecs.exporters.opencode import OpenCodeExtractor


FIXTURE_STORAGE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "opencode" / "storage"
)
FIXTURE_SQLITE_STORAGE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "opencode" / "sqlite" / "storage"
)


def make_extractor(storage_root: Path, cwd: Path, monkeypatch) -> OpenCodeExtractor:
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    extractor = OpenCodeExtractor()
    extractor.storage_root = storage_root
    return extractor


def test_extracts_realistic_opencode_session_fixture(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-project"
    extractor = make_extractor(FIXTURE_STORAGE, project_dir, monkeypatch)

    chats = extractor.extract_chats()

    assert len(chats) == 1
    chat = chats[0]
    assert chat["session_id"] == "ses_3f79fd355ffe0mH9k1yc0aO55K"
    assert chat["project"]["name"] == "sample-app"
    assert chat["project"]["rootPath"] == "/Users/redacted/work/project/sample-app"
    assert chat["session"]["title"] == "将 sample/grpc 设为默认上下文目录"
    assert chat["metadata"]["opencode_version"] == "1.1.40"
    assert chat["metadata"]["project_id"] == "project-fixture"
    assert chat["metadata"]["slug"] == "cosmic-meadow"
    assert len(chat["metadata"]["source_files"]) == 22

    messages = chat["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "assistant",
        "system",
        "assistant",
        "system",
        "user",
        "user",
        "user",
        "user",
        "assistant",
        "system",
        "system",
    ]
    assert messages[0]["content"] == "接下来所有的生成和上下文在这个目录：sample/grpc"
    assert messages[1]["content"] == "我会先检查该目录是否存在。"
    assert "Tool Call: bash" in messages[2]["content"]
    assert (
        '"command": "ls -la \\"sample/grpc\\" 2>/dev/null || echo \\"目录不存在\\""'
        in messages[2]["content"]
    )
    assert "total 8" in messages[3]["content"]
    assert "Tool Call: bash" in messages[4]["content"]
    assert "/Users/redacted/work/project/sample-app" in messages[5]["content"]
    assert "提供一份技术方案文档" in messages[6]["content"]
    assert "File Reference: sample/grpc/背景.md" in messages[7]["content"]
    assert '"path": "sample/grpc/背景.md"' in messages[7]["content"]
    assert "Called the Read tool" in messages[8]["content"]
    assert "<file>" in messages[9]["content"]
    assert "Tool Call: background_output" in messages[10]["content"]
    assert "Task ID" in messages[11]["content"]
    assert "Patch: fixture-patch-hash-001" in messages[12]["content"]
    assert (
        "/Users/redacted/work/project/sample-app/configs/virtual-service.yaml"
        in messages[12]["content"]
    )
    assert all("用户要求接下来" not in message["content"] for message in messages)
    assert all("compaction" not in message["content"] for message in messages)


def test_list_sessions_uses_title_preview_and_formatted_date(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-project"
    extractor = make_extractor(FIXTURE_STORAGE, project_dir, monkeypatch)

    sessions = extractor.list_sessions()

    assert len(sessions) == 1
    expected_date = datetime.fromtimestamp(1769667046570 / 1000).strftime(
        "%Y-%m-%d %H:%M"
    )
    assert sessions[0]["session_id"] == "ses_3f79fd355ffe0mH9k1yc0aO55K"
    assert sessions[0]["project"] == "sample-app"
    assert sessions[0]["date"] == expected_date
    assert sessions[0]["message_count"] == 13
    assert sessions[0]["preview"] == "将 sample/grpc 设为默认上下文目录"
    assert sessions[0]["source_files"] == 22


def test_extracts_sqlite_backed_opencode_session_fixture(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-project"
    extractor = make_extractor(FIXTURE_SQLITE_STORAGE, project_dir, monkeypatch)

    chats = extractor.extract_chats()

    assert len(chats) == 1
    chat = chats[0]
    assert chat["session_id"] == "ses_sqlite_fixture_001"
    assert chat["project"]["name"] == "sqlite-app"
    assert chat["project"]["rootPath"] == "/Users/redacted/work/project/sqlite-app"
    assert chat["session"]["title"] == "SQLite backed session"
    assert chat["metadata"]["opencode_version"] == "1.2.24"
    assert chat["metadata"]["project_id"] == "proj_sqlite_fixture"
    assert chat["metadata"]["workspace_id"] == "ws_sqlite_fixture"
    assert chat["metadata"]["slug"] == "sqlite-meadow"
    assert chat["metadata"]["summary"] == {
        "additions": 12,
        "deletions": 3,
        "files": 1,
        "diffs": ["configs/sqlite.yaml"],
    }
    assert len(chat["metadata"]["source_files"]) == 12
    assert all("#" in source for source in chat["metadata"]["source_files"])

    messages = chat["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "assistant",
        "system",
        "user",
        "system",
    ]
    assert messages[0]["content"] == "请检查 sqlite 导出是否工作"
    assert messages[1]["content"] == "我会先读取 SQLite 数据库结构。"
    assert "Tool Call: bash" in messages[2]["content"]
    assert '"command": "sqlite3 opencode.db \\".tables\\""' in messages[2]["content"]
    assert "session\nmessage\npart" in messages[3]["content"]
    assert "File Reference: docs/sqlite.md" in messages[4]["content"]
    assert '"path": "docs/sqlite.md"' in messages[4]["content"]
    assert "Patch: sqlite-patch-001" in messages[5]["content"]
    assert all("internal" not in message["content"] for message in messages)
    assert all("ignore me" not in message["content"] for message in messages)


def test_list_sessions_reads_sqlite_fixture(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-project"
    extractor = make_extractor(FIXTURE_SQLITE_STORAGE, project_dir, monkeypatch)

    sessions = extractor.list_sessions()

    assert len(sessions) == 1
    expected_date = datetime.fromtimestamp(1769667000000 / 1000).strftime(
        "%Y-%m-%d %H:%M"
    )
    assert sessions[0]["session_id"] == "ses_sqlite_fixture_001"
    assert sessions[0]["project"] == "sqlite-app"
    assert sessions[0]["date"] == expected_date
    assert sessions[0]["message_count"] == 6
    assert sessions[0]["preview"] == "SQLite backed session"
    assert sessions[0]["source_files"] == 12


def test_extracts_sqlite_fixture_when_storage_path_contains_spaces(
    tmp_path,
    monkeypatch,
):
    fixture_root = tmp_path / "opencode fixture with spaces"
    shutil.copytree(FIXTURE_SQLITE_STORAGE.parent, fixture_root)
    extractor = make_extractor(fixture_root / "storage", tmp_path / "workspace", monkeypatch)

    chats = extractor.extract_chats()

    assert len(chats) == 1
    assert chats[0]["session_id"] == "ses_sqlite_fixture_001"
    assert chats[0]["messages"][0]["content"] == "请检查 sqlite 导出是否工作"


def test_falls_back_to_legacy_storage_when_sqlite_schema_is_incomplete(
    tmp_path,
    monkeypatch,
    caplog,
):
    fixture_root = tmp_path / "opencode"
    shutil.copytree(FIXTURE_STORAGE.parent, fixture_root)
    sqlite_path = fixture_root / "opencode.db"

    with closing(sqlite3.connect(sqlite_path)) as connection:
        connection.execute("CREATE TABLE session (id text PRIMARY KEY)")
        connection.commit()

    extractor = make_extractor(fixture_root / "storage", tmp_path / "workspace", monkeypatch)

    with caplog.at_level(logging.WARNING):
        chats = extractor.extract_chats()

    assert len(chats) == 1
    assert chats[0]["session_id"] == "ses_3f79fd355ffe0mH9k1yc0aO55K"
    assert any("missing required tables" in record.message for record in caplog.records)
