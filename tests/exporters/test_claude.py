import json
from pathlib import Path

from anyspecs.exporters.claude import ClaudeExtractor


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_extractor(projects_root: Path, cwd: Path, monkeypatch) -> ClaudeExtractor:
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    extractor = ClaudeExtractor()
    extractor.projects_root = projects_root
    return extractor


def test_extracts_sessions_by_scanning_all_claude_project_dirs(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude" / "projects"
    current_dir = tmp_path / "work" / "project" / "anyspecs-cli"
    claude_project_dir = (
        projects_root / "-Users-liang2h-ensoai-workspaces-jzx-composition-feature-20260206-ghp-v1"
    )
    session_file = claude_project_dir / "b7a2d4db-f191-4c1e-aa97-547b81d990c3.jsonl"
    session_cwd = "/Users/liang2h/ensoai/workspaces/jzx-composition/feature/20260206-ghp-v1"

    write_jsonl(
        session_file,
        [
            {
                "type": "user",
                "sessionId": "b7a2d4db-f191-4c1e-aa97-547b81d990c3",
                "cwd": session_cwd,
                "version": "2.1.63",
                "timestamp": "2026-03-19T07:14:03.163Z",
                "message": {
                    "role": "user",
                    "content": "请检查 Claude 导出器",
                },
            },
            {
                "type": "assistant",
                "sessionId": "b7a2d4db-f191-4c1e-aa97-547b81d990c3",
                "cwd": session_cwd,
                "version": "2.1.63",
                "timestamp": "2026-03-19T07:14:05.163Z",
                "message": {
                    "role": "assistant",
                    "type": "message",
                    "content": [{"type": "text", "text": "我来检查。"}],
                },
            },
        ],
    )

    extractor = make_extractor(projects_root, current_dir, monkeypatch)
    chats = extractor.extract_chats()

    assert len(chats) == 1
    chat = chats[0]
    assert chat["session"]["sessionId"] == "b7a2d4db-f191-4c1e-aa97-547b81d990c3"
    assert chat["project"]["rootPath"] == session_cwd
    assert chat["project"]["name"] == "20260206-ghp-v1"
    assert chat["metadata"]["claude_version"] == "2.1.63"
    assert len(chat["messages"]) == 2
    assert chat["messages"][0]["content"] == "请检查 Claude 导出器"
    assert chat["messages"][1]["content"] == "我来检查。"


def test_parses_text_tool_blocks_and_ignores_internal_records(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude" / "projects"
    current_dir = tmp_path / "work" / "project" / "anyspecs-cli"
    claude_project_dir = projects_root / "-Users-liang2h-work-project-pks"
    session_file = claude_project_dir / "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb.jsonl"
    session_cwd = "/Users/liang2h/work/project/pks"

    write_jsonl(
        session_file,
        [
            {
                "type": "file-history-snapshot",
                "messageId": "ignored",
                "snapshot": {"timestamp": "2026-03-19T07:14:00.000Z"},
            },
            {
                "type": "user",
                "sessionId": "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb",
                "cwd": session_cwd,
                "version": "2.1.71",
                "timestamp": "2026-03-19T07:14:03.163Z",
                "message": {
                    "role": "user",
                    "content": "status",
                },
            },
            {
                "type": "assistant",
                "sessionId": "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb",
                "cwd": session_cwd,
                "version": "2.1.71",
                "timestamp": "2026-03-19T07:14:04.163Z",
                "message": {
                    "role": "assistant",
                    "type": "message",
                    "content": [
                        {"type": "thinking", "thinking": "ignored"},
                        {"type": "text", "text": "正在检查。"},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Grep",
                            "input": {"pattern": "status", "output_mode": "content"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "sessionId": "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb",
                "cwd": session_cwd,
                "version": "2.1.71",
                "timestamp": "2026-03-19T07:14:05.163Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "No files found",
                        }
                    ],
                },
            },
            {
                "type": "progress",
                "sessionId": "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb",
                "cwd": session_cwd,
                "timestamp": "2026-03-19T07:14:06.163Z",
                "data": {"type": "hook_progress"},
            },
            {
                "type": "system",
                "sessionId": "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb",
                "cwd": session_cwd,
                "timestamp": "2026-03-19T07:14:07.163Z",
                "subtype": "stop_hook_summary",
            },
            {
                "type": "last-prompt",
                "sessionId": "c24a0d82-89b9-4b6e-b8b4-a5095217d8fb",
                "lastPrompt": "ignored",
            },
        ],
    )

    extractor = make_extractor(projects_root, current_dir, monkeypatch)
    chats = extractor.extract_chats()

    assert len(chats) == 1
    messages = chats[0]["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "assistant",
        "system",
    ]
    assert messages[0]["content"] == "status"
    assert messages[1]["content"] == "正在检查。"
    assert "Tool Call: Grep" in messages[2]["content"]
    assert '"pattern": "status"' in messages[2]["content"]
    assert "Tool Result: toolu_1" in messages[3]["content"]
    assert "No files found" in messages[3]["content"]
    assert all("ignored" not in message["content"] for message in messages)


def test_list_sessions_formats_preview_and_date(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude" / "projects"
    current_dir = tmp_path / "work" / "project" / "anyspecs-cli"
    claude_project_dir = projects_root / "-Users-liang2h-work-self-work-agent-content-security"
    session_file = claude_project_dir / "11111111-2222-3333-4444-555555555555.jsonl"
    session_cwd = "/Users/liang2h/work/self/work-agent-content-security"

    write_jsonl(
        session_file,
        [
            {
                "type": "user",
                "sessionId": "11111111-2222-3333-4444-555555555555",
                "cwd": session_cwd,
                "version": "2.1.71",
                "timestamp": "2026-03-19T07:14:03.163Z",
                "message": {
                    "role": "user",
                    "content": "这是一个很长的预览消息，用来验证 Claude list_sessions 的 preview 和 date 格式是否正常工作。",
                },
            }
        ],
    )

    extractor = make_extractor(projects_root, current_dir, monkeypatch)
    sessions = extractor.list_sessions()

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "11111111"
    assert sessions[0]["project"] == "work-agent-content-security"
    assert sessions[0]["message_count"] == 1
    assert sessions[0]["date"] == "2026-03-19 15:14"
    assert sessions[0]["preview"].startswith("这是一个很长的预览消息")


def test_reports_supported_and_unsupported_claude_versions(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude" / "projects"
    current_dir = tmp_path / "work" / "project" / "anyspecs-cli"
    supported_file = projects_root / "-Users-liang2h-work-project-pks" / "a.jsonl"
    unsupported_file = projects_root / "-Users-liang2h-work-project-pks" / "b.jsonl"

    write_jsonl(
        supported_file,
        [
            {
                "type": "user",
                "sessionId": "11111111-2222-3333-4444-555555555555",
                "cwd": "/Users/liang2h/work/project/pks",
                "version": "2.1.71",
                "timestamp": "2026-03-19T07:14:03.163Z",
                "message": {"role": "user", "content": "status"},
            }
        ],
    )
    write_jsonl(
        unsupported_file,
        [
            {
                "type": "user",
                "sessionId": "66666666-7777-8888-9999-000000000000",
                "cwd": "/Users/liang2h/work/project/pks",
                "version": "2.1.73",
                "timestamp": "2026-03-19T07:14:03.163Z",
                "message": {"role": "user", "content": "status"},
            }
        ],
    )

    extractor = make_extractor(projects_root, current_dir, monkeypatch)
    info = extractor.get_version_support_info()

    assert info["has_sessions"] is True
    assert info["supported_versions"] == [
        "1.0.98",
        "2.1.59",
        "2.1.62",
        "2.1.63",
        "2.1.71",
        "2.1.72",
    ]
    assert info["detected_versions"] == ["2.1.71", "2.1.73"]
    assert info["unsupported_versions"] == ["2.1.73"]


def test_reports_no_claude_version_info_when_no_history_exists(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude" / "projects"
    current_dir = tmp_path / "work" / "project" / "anyspecs-cli"

    extractor = make_extractor(projects_root, current_dir, monkeypatch)
    info = extractor.get_version_support_info()

    assert info["has_sessions"] is False
    assert info["detected_versions"] == []
    assert info["unsupported_versions"] == []
