import json
from pathlib import Path

from anyspecs.exporters.codex import CodexExtractor


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_extractor(history_dir: Path, cwd: Path, monkeypatch) -> CodexExtractor:
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    extractor = CodexExtractor()
    extractor.history_dir = history_dir
    return extractor


def test_extracts_real_codex_sessions_with_messages_and_tools(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"
    session_id = "019d04f1-b713-7701-9c80-a9752539fa7f"
    session_file = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "19"
        / f"rollout-2026-03-19T15-14-03-{session_id}.jsonl"
    )

    write_jsonl(
        history_dir / "session_index.jsonl",
        [
            {
                "id": session_id,
                "thread_name": "修复Codex导出器无法提取会话记录",
                "updated_at": "2026-03-19T07:18:37.826419Z",
            }
        ],
    )
    write_jsonl(
        session_file,
        [
            {
                "timestamp": "2026-03-19T07:14:03.163Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-03-19T07:14:03.163Z",
                    "cwd": str(project_dir),
                    "cli_version": "0.115.0-alpha.27",
                    "source": "vscode",
                    "model_provider": "openai",
                },
            },
            {
                "timestamp": "2026-03-19T07:14:04.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "developer prompt"}],
                },
            },
            {
                "timestamp": "2026-03-19T07:14:05.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "请修复导出器"}],
                },
            },
            {
                "timestamp": "2026-03-19T07:14:06.000Z",
                "type": "response_item",
                "payload": {"type": "reasoning", "encrypted_content": "ignored"},
            },
            {
                "timestamp": "2026-03-19T07:14:07.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "我来处理。"}],
                },
            },
            {
                "timestamp": "2026-03-19T07:14:08.000Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": "{\"cmd\":\"pwd\"}",
                    "call_id": "call_1",
                },
            },
            {
                "timestamp": "2026-03-19T07:14:09.000Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "Command output",
                },
            },
            {
                "timestamp": "2026-03-19T07:14:10.000Z",
                "type": "event_msg",
                "payload": {"type": "token_count"},
            },
        ],
    )

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    chats = extractor.extract_chats()

    assert len(chats) == 1
    chat = chats[0]
    assert chat["session_id"] == session_id
    assert chat["project"]["rootPath"] == str(project_dir)
    assert chat["project"]["name"] == "demo-app"
    assert chat["metadata"]["thread_name"] == "修复Codex导出器无法提取会话记录"
    assert chat["session"]["title"] == "修复Codex导出器无法提取会话记录"
    assert chat["metadata"]["source_kind"] == "session"
    assert [message["role"] for message in chat["messages"]] == [
        "user",
        "assistant",
        "assistant",
        "system",
    ]
    assert chat["messages"][0]["content"] == "请修复导出器"
    assert "Function Call: exec_command" in chat["messages"][2]["content"]
    assert "Function Output: call_1" in chat["messages"][3]["content"]
    assert all("developer prompt" not in message["content"] for message in chat["messages"])

    listed = extractor.list_sessions()
    assert listed[0]["project"] == "demo-app"
    assert listed[0]["preview"] == "修复Codex导出器无法提取会话记录"


def test_preserves_custom_tool_and_web_search_records(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"
    session_id = "019cce3a-c23a-7080-9ec3-0364124b1c11"
    session_file = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "09"
        / f"rollout-2026-03-09T00-14-43-{session_id}.jsonl"
    )

    write_jsonl(
        session_file,
        [
            {
                "timestamp": "2026-03-09T02:30:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-03-09T02:30:00.000Z",
                    "cwd": str(project_dir),
                },
            },
            {
                "timestamp": "2026-03-09T02:37:25.477Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "status": "completed",
                    "call_id": "call_patch",
                    "name": "apply_patch",
                    "input": "*** Begin Patch\n*** End Patch",
                },
            },
            {
                "timestamp": "2026-03-09T02:37:25.530Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call_patch",
                    "output": "{\"output\":\"Success\"}",
                },
            },
            {
                "timestamp": "2026-03-09T02:38:00.000Z",
                "type": "response_item",
                "payload": {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"type": "search", "query": "codex exporter"},
                },
            },
        ],
    )

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    chats = extractor.extract_chats()

    assert len(chats) == 1
    messages = chats[0]["messages"]
    assert len(messages) == 3
    assert "Tool Call: apply_patch" in messages[0]["content"]
    assert "Tool Output: call_patch" in messages[1]["content"]
    assert "Web Search" in messages[2]["content"]
    assert "\"query\": \"codex exporter\"" in messages[2]["content"]


def test_uses_history_as_fallback_without_duplicating_real_sessions(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"
    real_session_id = "019cae10-44e1-7a20-9071-748e4c03c192"
    fallback_session_id = "019cae10-44e1-7a20-9071-748e4c03c199"
    session_file = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "02"
        / f"rollout-2026-03-02T18-20-27-{real_session_id}.jsonl"
    )

    write_jsonl(
        session_file,
        [
            {
                "timestamp": "2026-03-02T10:20:37.166Z",
                "type": "session_meta",
                "payload": {
                    "id": real_session_id,
                    "timestamp": "2026-03-02T10:20:37.166Z",
                    "cwd": str(project_dir),
                },
            },
            {
                "timestamp": "2026-03-02T10:20:38.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "真实会话"}],
                },
            },
        ],
    )
    write_jsonl(
        history_dir / "history.jsonl",
        [
            {"session_id": real_session_id, "ts": 1772446837, "text": "history duplicate"},
            {"session_id": fallback_session_id, "ts": 1772446840, "text": "history only"},
        ],
    )

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    chats = extractor.extract_chats()

    assert len(chats) == 2
    by_id = {chat["session_id"]: chat for chat in chats}
    assert [message["content"] for message in by_id[real_session_id]["messages"]] == [
        "真实会话"
    ]
    assert by_id[fallback_session_id]["metadata"]["source_kind"] == "history"
    assert by_id[fallback_session_id]["metadata"]["fallback_only"] is True
    assert by_id[fallback_session_id]["project"]["name"] == "Unknown Project"
    assert [message["content"] for message in by_id[fallback_session_id]["messages"]] == [
        "history only"
    ]


def test_keeps_config_and_log_as_synthetic_sessions(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"
    log_dir = history_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "config.toml").write_text(
        f'model = "gpt-5.4"\n[projects."{project_dir}"]\ntrust_level = "trusted"\n',
        encoding="utf-8",
    )
    (log_dir / "codex-tui.log").write_text(
        f"project log for {project_dir}\n",
        encoding="utf-8",
    )

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    chats = extractor.extract_chats()

    synthetic = {chat["metadata"]["source_kind"]: chat for chat in chats}
    assert synthetic["config"]["metadata"]["synthetic"] is True
    assert synthetic["log"]["metadata"]["synthetic"] is True
    assert synthetic["config"]["project"]["rootPath"] == str(project_dir)
    assert synthetic["log"]["project"]["name"] == "demo-app"
    assert "Project configuration" in synthetic["config"]["messages"][0]["content"]
    assert "Log entries related to project" in synthetic["log"]["messages"][0]["content"]


def test_reports_supported_and_unsupported_codex_versions(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"
    supported_session = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "11"
        / "rollout-2026-03-11T14-13-30-019cdb87-686a-7253-b2f3-ef7ec0c4122b.jsonl"
    )
    unsupported_session = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "21"
        / "rollout-2026-03-21T14-13-30-019cdb87-686a-7253-b2f3-ef7ec0c4999.jsonl"
    )

    write_jsonl(
        supported_session,
        [
            {
                "timestamp": "2026-03-11T06:13:30.350Z",
                "type": "session_meta",
                "payload": {
                    "id": "019cdb87-686a-7253-b2f3-ef7ec0c4122b",
                    "timestamp": "2026-03-11T06:13:30.350Z",
                    "cwd": str(project_dir),
                    "cli_version": "0.114.0",
                },
            }
        ],
    )
    write_jsonl(
        unsupported_session,
        [
            {
                "timestamp": "2026-03-21T06:13:30.350Z",
                "type": "session_meta",
                "payload": {
                    "id": "019cdb87-686a-7253-b2f3-ef7ec0c4999",
                    "timestamp": "2026-03-21T06:13:30.350Z",
                    "cwd": str(project_dir),
                    "cli_version": "0.115.0-alpha.28",
                },
            }
        ],
    )

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    info = extractor.get_version_support_info()

    assert info["has_sessions"] is True
    assert info["supported_versions"] == [
        "0.106.0",
        "0.111.0",
        "0.114.0",
        "0.115.0-alpha.27",
    ]
    assert info["detected_versions"] == ["0.114.0", "0.115.0-alpha.28"]
    assert info["unsupported_versions"] == ["0.115.0-alpha.28"]


def test_reports_no_codex_version_info_when_no_sessions_exist(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    info = extractor.get_version_support_info()

    assert info["has_sessions"] is False
    assert info["detected_versions"] == []
    assert info["unsupported_versions"] == []


def test_extracts_project_name_from_windows_cwd_paths(tmp_path, monkeypatch):
    history_dir = tmp_path / ".codex"
    project_dir = tmp_path / "workspace" / "demo-app"
    desktop_session_id = "019d04f1-b713-7701-9c80-a9752539fa70"
    workspace_session_id = "019d04f1-b713-7701-9c80-a9752539fa71"
    desktop_session = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "20"
        / f"rollout-2026-03-20T10-00-00-{desktop_session_id}.jsonl"
    )
    workspace_session = (
        history_dir
        / "sessions"
        / "2026"
        / "03"
        / "20"
        / f"rollout-2026-03-20T10-05-00-{workspace_session_id}.jsonl"
    )

    write_jsonl(
        desktop_session,
        [
            {
                "timestamp": "2026-03-20T02:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": desktop_session_id,
                    "timestamp": "2026-03-20T02:00:00.000Z",
                    "cwd": r"C:\Users\15257\Desktop\jzx-devops-all",
                },
            },
            {
                "timestamp": "2026-03-20T02:00:01.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "desktop project"}],
                },
            },
        ],
    )
    write_jsonl(
        workspace_session,
        [
            {
                "timestamp": "2026-03-20T02:05:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": workspace_session_id,
                    "timestamp": "2026-03-20T02:05:00.000Z",
                    "cwd": r"C:\workspace\demo-app",
                },
            },
            {
                "timestamp": "2026-03-20T02:05:01.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "workspace project"}],
                },
            },
        ],
    )

    extractor = make_extractor(history_dir, project_dir, monkeypatch)
    chats = extractor.extract_chats()

    by_id = {chat["session_id"]: chat for chat in chats}
    assert by_id[desktop_session_id]["project"]["name"] == "jzx-devops-all"
    assert by_id[desktop_session_id]["project"]["rootPath"] == r"C:\Users\15257\Desktop\jzx-devops-all"
    assert by_id[workspace_session_id]["project"]["name"] == "demo-app"
    assert by_id[workspace_session_id]["project"]["rootPath"] == r"C:\workspace\demo-app"
