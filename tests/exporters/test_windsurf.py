import copy
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from anyspecs.config.runtime import config as runtime_config
from anyspecs.exporters.windsurf import WindsurfExtractor
from anyspecs.utils.paths import (
    resolve_windsurf_app_root,
    resolve_windsurf_extension_bundle_path,
    resolve_windsurf_storage_root,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "windsurf" / "storage"
ACTIVE_SESSION_ID = "cbc99144-4e48-4e68-89f7-3f1608611bbe"
HISTORICAL_SESSION_ID = "f32adc43-5d83-41e5-ab27-736a817cf70d"
WORKSPACE_ID = "359c582b8bf0e42edf8be0b6be435fa6"


def copy_fixture_storage(tmp_path: Path) -> Path:
    storage_copy = tmp_path / "windsurf-storage"
    shutil.copytree(FIXTURE_ROOT, storage_copy)
    return storage_copy


def install_fixture_pb_decoder(monkeypatch) -> None:
    def fake_fetch_workspace_trajectories(
        self,
        workspace_id,
        session_ids,
        binary_path,
        node_binary,
    ):
        decoded = {}
        errors = {}
        decoded_root = self.storage_root / "decoded"
        for session_id in session_ids:
            decoded_path = decoded_root / f"{session_id}.json"
            if decoded_path.exists():
                decoded[session_id] = json.loads(decoded_path.read_text(encoding="utf-8"))
            else:
                errors[session_id] = f"Missing decoded Windsurf fixture for session '{session_id}'."
        return decoded, errors

    monkeypatch.setattr(
        WindsurfExtractor,
        "_fetch_workspace_trajectories",
        fake_fetch_workspace_trajectories,
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_get_language_server_binary",
        lambda self: Path(__file__),
    )


def make_extractor(storage_base: Path, cwd: Path, monkeypatch) -> WindsurfExtractor:
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    extractor = WindsurfExtractor()
    extractor.app_root = storage_base / "app"
    extractor.storage_root = storage_base / "codeium"
    extractor.extension_bundle_path = Path(__file__)
    return extractor


def test_extracts_multiple_windsurf_sessions_and_historical_pb_content(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    chats = extractor.extract_chats()

    assert len(chats) == 2
    by_id = {chat["session_id"]: chat for chat in chats}

    active_chat = by_id[ACTIVE_SESSION_ID]
    assert active_chat["project"]["name"] == "demo-learning-platform"
    assert active_chat["metadata"]["storage_kind"] == "windsurf_pb"
    assert len(active_chat["messages"]) == 3
    assert active_chat["messages"][0]["content"] == "介绍下项目概况"
    assert "# 项目概况" in active_chat["messages"][2]["content"]

    historical_chat = by_id[HISTORICAL_SESSION_ID]
    assert historical_chat["metadata"]["storage_kind"] == "windsurf_pb"
    assert historical_chat["session"]["title"] == "Data Model Review"
    assert [message["role"] for message in historical_chat["messages"]] == [
        "user",
        "assistant",
        "assistant",
    ]
    assert historical_chat["messages"][0]["content"] == "梳理一下核心数据模型"
    assert "我先梳理关键领域对象" in historical_chat["messages"][1]["content"]
    assert "核心数据模型" in historical_chat["messages"][2]["content"]


def test_extract_chats_for_export_only_decodes_requested_session(tmp_path, monkeypatch):
    calls = []

    def fake_fetch_workspace_trajectories(
        self,
        workspace_id,
        session_ids,
        binary_path,
        node_binary,
    ):
        calls.append((workspace_id, list(session_ids)))
        decoded = {}
        decoded_root = self.storage_root / "decoded"
        for session_id in session_ids:
            decoded_path = decoded_root / f"{session_id}.json"
            decoded[session_id] = json.loads(decoded_path.read_text(encoding="utf-8"))
        return decoded, {}

    monkeypatch.setattr(
        WindsurfExtractor,
        "_fetch_workspace_trajectories",
        fake_fetch_workspace_trajectories,
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_get_language_server_binary",
        lambda self: Path(__file__),
    )

    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )
    index_context = extractor.get_index_context()

    chats = extractor.extract_chats_for_export(
        session_ids=[HISTORICAL_SESSION_ID],
        index_context=index_context,
    )

    assert [chat["session_id"] for chat in chats] == [HISTORICAL_SESSION_ID]
    assert calls == [(WORKSPACE_ID, [HISTORICAL_SESSION_ID])]


def test_command_scope_reuses_workspace_server_for_same_workspace(tmp_path, monkeypatch):
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    start_calls = []
    stop_calls = []
    cleanup_calls = []

    class DummyProcess:
        def __init__(self):
            self.exit_code = None

        def poll(self):
            return self.exit_code

        def terminate(self):
            self.exit_code = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.exit_code = -9

    def fake_start_workspace_server(self, workspace_id, binary_path, node_binary):
        start_calls.append((workspace_id, str(binary_path), node_binary))
        return (
            {
                "workspace_id": workspace_id,
                "process": DummyProcess(),
                "manager_dir": tmp_path / f"manager-{len(start_calls)}",
                "csrf_token": f"csrf-{len(start_calls)}",
                "base_url": f"http://127.0.0.1:{43000 + len(start_calls)}",
            },
            None,
        )

    def fake_run_node_json(self, node_binary, script, payload, error_context):
        del self, node_binary, script, error_context
        return {
            "trajectories": {
                session_id: {"sessionId": session_id}
                for session_id in payload["session_ids"]
            },
            "errors": {},
        }

    monkeypatch.setattr(
        WindsurfExtractor,
        "_start_workspace_server",
        fake_start_workspace_server,
    )
    monkeypatch.setattr(WindsurfExtractor, "_run_node_json", fake_run_node_json)
    monkeypatch.setattr(
        WindsurfExtractor,
        "_stop_language_server",
        lambda self, process: stop_calls.append(process),
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_cleanup_manager_dir",
        lambda self, manager_dir: cleanup_calls.append(Path(manager_dir)),
    )

    extractor.begin_command_scope()
    try:
        decoded_one, errors_one = extractor._fetch_workspace_trajectories(
            workspace_id=WORKSPACE_ID,
            session_ids=[ACTIVE_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
        decoded_two, errors_two = extractor._fetch_workspace_trajectories(
            workspace_id=WORKSPACE_ID,
            session_ids=[HISTORICAL_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
    finally:
        extractor.close_command_scope()

    assert errors_one == {}
    assert errors_two == {}
    assert decoded_one == {ACTIVE_SESSION_ID: {"sessionId": ACTIVE_SESSION_ID}}
    assert decoded_two == {HISTORICAL_SESSION_ID: {"sessionId": HISTORICAL_SESSION_ID}}
    assert start_calls == [(WORKSPACE_ID, str(Path(__file__)), "node")]
    assert len(stop_calls) == 1
    assert len(cleanup_calls) == 1


def test_command_scope_starts_distinct_servers_per_workspace(tmp_path, monkeypatch):
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    start_calls = []

    class DummyProcess:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    def fake_start_workspace_server(self, workspace_id, binary_path, node_binary):
        del self, binary_path, node_binary
        start_calls.append(workspace_id)
        return (
            {
                "workspace_id": workspace_id,
                "process": DummyProcess(),
                "manager_dir": tmp_path / f"manager-{workspace_id}",
                "csrf_token": f"csrf-{workspace_id}",
                "base_url": f"http://127.0.0.1:{43000 + len(start_calls)}",
            },
            None,
        )

    monkeypatch.setattr(
        WindsurfExtractor,
        "_start_workspace_server",
        fake_start_workspace_server,
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_run_node_json",
        lambda self, node_binary, script, payload, error_context: {
            "trajectories": {
                session_id: {"sessionId": session_id}
                for session_id in payload["session_ids"]
            },
            "errors": {},
        },
    )
    monkeypatch.setattr(WindsurfExtractor, "_stop_language_server", lambda self, process: None)
    monkeypatch.setattr(WindsurfExtractor, "_cleanup_manager_dir", lambda self, manager_dir: None)

    extractor.begin_command_scope()
    try:
        extractor._fetch_workspace_trajectories(
            workspace_id=WORKSPACE_ID,
            session_ids=[ACTIVE_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
        extractor._fetch_workspace_trajectories(
            workspace_id="other-workspace",
            session_ids=[HISTORICAL_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
    finally:
        extractor.close_command_scope()

    assert start_calls == [WORKSPACE_ID, "other-workspace"]


def test_fetch_workspace_trajectories_restarts_dead_cached_server_once(tmp_path, monkeypatch):
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    start_calls = []
    stop_calls = []
    cleanup_calls = []

    class DummyProcess:
        def __init__(self, exit_code):
            self.exit_code = exit_code

        def poll(self):
            return self.exit_code

        def terminate(self):
            self.exit_code = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.exit_code = -9

    def fake_start_workspace_server(self, workspace_id, binary_path, node_binary):
        del self, binary_path, node_binary
        start_calls.append(workspace_id)
        process = DummyProcess(1 if len(start_calls) == 1 else None)
        return (
            {
                "workspace_id": workspace_id,
                "process": process,
                "manager_dir": tmp_path / f"manager-{len(start_calls)}",
                "csrf_token": f"csrf-{len(start_calls)}",
                "base_url": f"http://127.0.0.1:{43000 + len(start_calls)}",
            },
            None,
        )

    monkeypatch.setattr(
        WindsurfExtractor,
        "_start_workspace_server",
        fake_start_workspace_server,
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_run_node_json",
        lambda self, node_binary, script, payload, error_context: {
            "trajectories": {
                session_id: {"sessionId": session_id}
                for session_id in payload["session_ids"]
            },
            "errors": {},
        },
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_stop_language_server",
        lambda self, process: stop_calls.append(process),
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_cleanup_manager_dir",
        lambda self, manager_dir: cleanup_calls.append(Path(manager_dir)),
    )

    extractor.begin_command_scope()
    try:
        decoded, errors = extractor._fetch_workspace_trajectories(
            workspace_id=WORKSPACE_ID,
            session_ids=[ACTIVE_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
    finally:
        extractor.close_command_scope()

    assert errors == {}
    assert decoded == {ACTIVE_SESSION_ID: {"sessionId": ACTIVE_SESSION_ID}}
    assert start_calls == [WORKSPACE_ID, WORKSPACE_ID]
    assert len(stop_calls) == 2
    assert len(cleanup_calls) == 2


def test_begin_command_scope_clears_previous_workspace_servers(tmp_path, monkeypatch):
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    stopped = []
    cleaned = []

    class DummyProcess:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(
        WindsurfExtractor,
        "_stop_language_server",
        lambda self, process: stopped.append(process),
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_cleanup_manager_dir",
        lambda self, manager_dir: cleaned.append(Path(manager_dir)),
    )

    extractor._workspace_servers[WORKSPACE_ID] = {
        "process": DummyProcess(),
        "manager_dir": tmp_path / "stale-manager",
    }

    extractor.begin_command_scope()

    assert extractor._command_scope_active is True
    assert extractor._workspace_servers == {}
    assert len(stopped) == 1
    assert len(cleaned) == 1


def test_list_sessions_lists_all_project_sessions(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    sessions = extractor.list_sessions()

    assert len(sessions) == 2
    by_id = {session["session_id"]: session for session in sessions}
    assert by_id["cbc99144"]["preview"] == "介绍下项目概况"
    assert by_id["cbc99144"]["message_count"] == 3
    assert by_id["f32adc43"]["preview"] == "Data Model Review"
    assert by_id["f32adc43"]["message_count"] == 0
    expected_date = datetime.fromtimestamp(1774347887599 / 1000).strftime("%Y-%m-%d %H:%M")
    assert by_id["cbc99144"]["date"] == expected_date


def test_list_sessions_does_not_trigger_pb_decoding(tmp_path, monkeypatch):
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("list_sessions should not decode pb trajectories")

    monkeypatch.setattr(
        WindsurfExtractor,
        "_fetch_workspace_trajectories",
        fail_if_called,
    )

    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    sessions = extractor.list_sessions()

    assert len(sessions) == 2
    assert calls == []


def test_historical_export_is_stable_when_active_cache_switches(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    storage_base = copy_fixture_storage(tmp_path)
    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    first_chat = next(
        chat for chat in extractor.extract_chats() if chat["session_id"] == ACTIVE_SESSION_ID
    )

    cache_path = storage_base / "codeium" / "cache_state.json"
    cache_state = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_state["workspaces"][0]["active_trajectory"] = {
        "cascadeId": HISTORICAL_SESSION_ID,
        "trajectory": {"trajectoryType": "CORTEX_TRAJECTORY_TYPE_CASCADE", "steps": []},
        "status": "CASCADE_RUN_STATUS_IDLE",
    }
    cache_path.write_text(json.dumps(cache_state, indent=2, ensure_ascii=False), encoding="utf-8")

    second_chat = next(
        chat for chat in extractor.extract_chats() if chat["session_id"] == ACTIVE_SESSION_ID
    )

    assert second_chat["metadata"]["storage_kind"] == "windsurf_pb"
    assert second_chat["messages"] == first_chat["messages"]


def test_missing_pb_only_falls_back_for_active_session(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    storage_base = copy_fixture_storage(tmp_path)
    (storage_base / "codeium" / "cascade" / f"{ACTIVE_SESSION_ID}.pb").unlink()
    (storage_base / "codeium" / "cascade" / f"{HISTORICAL_SESSION_ID}.pb").unlink()
    (storage_base / "codeium" / "decoded" / f"{ACTIVE_SESSION_ID}.json").unlink()
    (storage_base / "codeium" / "decoded" / f"{HISTORICAL_SESSION_ID}.json").unlink()

    extractor = make_extractor(
        storage_base,
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    chats = extractor.extract_chats()

    assert len(chats) == 1
    chat = chats[0]
    assert chat["session_id"] == ACTIVE_SESSION_ID
    assert chat["metadata"]["storage_kind"] == "windsurf_cache_active_fallback"
    assert extractor.get_session_export_error(HISTORICAL_SESSION_ID[:8]) is not None


def test_path_resolution_prefers_env_then_config_then_auto(tmp_path, monkeypatch):
    env_app_root = tmp_path / "env-app"
    env_storage_root = tmp_path / "env-storage"
    env_bundle_path = tmp_path / "env-bundle.js"
    env_app_root.mkdir()
    env_storage_root.mkdir()
    env_bundle_path.write_text("// env bundle", encoding="utf-8")

    config_app_root = tmp_path / "config-app"
    config_storage_root = tmp_path / "config-storage"
    config_bundle_path = tmp_path / "config-bundle.js"
    config_app_root.mkdir()
    config_storage_root.mkdir()
    config_bundle_path.write_text("// config bundle", encoding="utf-8")

    original_config = copy.deepcopy(runtime_config._config)
    runtime_config._config["sources"]["windsurf"]["app_root"] = str(config_app_root)
    runtime_config._config["sources"]["windsurf"]["storage_root"] = str(config_storage_root)
    runtime_config._config["sources"]["windsurf"]["extension_bundle_path"] = str(
        config_bundle_path
    )

    monkeypatch.setenv("ANYSPECS_WINDSURF_APP_ROOT", str(env_app_root))
    monkeypatch.setenv("ANYSPECS_WINDSURF_STORAGE_ROOT", str(env_storage_root))
    monkeypatch.setenv("ANYSPECS_WINDSURF_EXTENSION_BUNDLE", str(env_bundle_path))

    try:
        resolved_app_root, app_source = resolve_windsurf_app_root()
        resolved_storage_root, storage_source = resolve_windsurf_storage_root()
        resolved_bundle_path, bundle_source = resolve_windsurf_extension_bundle_path()

        assert resolved_app_root == env_app_root.resolve()
        assert resolved_storage_root == env_storage_root.resolve()
        assert resolved_bundle_path == env_bundle_path.resolve()
        assert app_source == "env:ANYSPECS_WINDSURF_APP_ROOT"
        assert storage_source == "env:ANYSPECS_WINDSURF_STORAGE_ROOT"
        assert bundle_source == "env:ANYSPECS_WINDSURF_EXTENSION_BUNDLE"

        monkeypatch.delenv("ANYSPECS_WINDSURF_APP_ROOT")
        monkeypatch.delenv("ANYSPECS_WINDSURF_STORAGE_ROOT")
        monkeypatch.delenv("ANYSPECS_WINDSURF_EXTENSION_BUNDLE")

        resolved_app_root, app_source = resolve_windsurf_app_root()
        resolved_storage_root, storage_source = resolve_windsurf_storage_root()
        resolved_bundle_path, bundle_source = resolve_windsurf_extension_bundle_path()

        assert resolved_app_root == config_app_root.resolve()
        assert resolved_storage_root == config_storage_root.resolve()
        assert resolved_bundle_path == config_bundle_path.resolve()
        assert app_source == "config:sources.windsurf.app_root"
        assert storage_source == "config:sources.windsurf.storage_root"
        assert bundle_source == "config:sources.windsurf.extension_bundle_path"
    finally:
        runtime_config._config = original_config


def test_run_node_json_decodes_utf8_bytes_without_platform_default_encoding(
    tmp_path, monkeypatch
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    def fake_run(*args, **kwargs):
        assert isinstance(kwargs["input"], bytes)
        assert kwargs["input"].decode("utf-8")
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout='{"message":"中文输出"}'.encode("utf-8"),
            stderr="".encode("utf-8"),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = extractor._run_node_json(
        node_binary="node",
        script="console.log('ok')",
        payload={"hello": "world"},
        error_context="Windows bytes decode",
    )

    assert result == {"message": "中文输出"}


def test_run_node_json_handles_non_utf8_stderr_bytes_without_crashing(
    tmp_path, monkeypatch, caplog
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout=b"",
            stderr=b"\x8e\x8fnode helper failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level("DEBUG", logger="anyspecs.extractors.windsurf"):
        result = extractor._run_node_json(
            node_binary="node",
            script="console.error('boom')",
            payload={"hello": "world"},
            error_context="Windows stderr decode",
        )

    assert result == {}
    assert "Windows stderr decode failed" in caplog.text


def test_run_node_json_logs_stdout_preview_for_invalid_json(
    tmp_path, monkeypatch, caplog
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="not-json-中文".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level("DEBUG", logger="anyspecs.extractors.windsurf"):
        result = extractor._run_node_json(
            node_binary="node",
            script="console.log('boom')",
            payload={"hello": "world"},
            error_context="Invalid JSON preview",
        )

    assert result == {}
    assert "Invalid JSON preview returned invalid JSON" in caplog.text
    assert "not-json-中文" in caplog.text


def test_debug_manager_dir_contents_handles_windows_style_transient_oserror(
    tmp_path, monkeypatch
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    class BrokenManagerDir:
        def exists(self):
            return True

        def rglob(self, pattern):
            raise OSError(267, "目录名称无效。")

    result = extractor._debug_manager_dir_contents(BrokenManagerDir())

    assert "unavailable" in result
    assert "267" in result


def test_find_language_server_port_file_returns_none_when_manager_dir_is_racy(
    tmp_path, monkeypatch
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    class BrokenManagerDir:
        def exists(self):
            return True

        def iterdir(self):
            raise OSError(267, "目录名称无效。")

    assert extractor._find_language_server_port_file(BrokenManagerDir()) is None


def test_wait_for_language_server_port_returns_none_when_debug_scan_hits_oserror(
    tmp_path, monkeypatch, caplog
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    class BrokenManagerDir:
        def exists(self):
            return True

        def iterdir(self):
            return iter(())

        def rglob(self, pattern):
            raise OSError(267, "目录名称无效。")

        def __truediv__(self, name):
            return self

    class ExitedProcess:
        def poll(self):
            return 1

    with caplog.at_level("DEBUG", logger="anyspecs.extractors.windsurf"):
        result = extractor._wait_for_language_server_port(
            process=ExitedProcess(),
            manager_dir=BrokenManagerDir(),
            timeout_seconds=1,
        )

    assert result is None
    assert "did not publish a port" in caplog.text


def test_fetch_workspace_trajectories_returns_timeout_error_instead_of_raising(
    tmp_path, monkeypatch
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )
    extractor.extension_bundle_path = Path(__file__)

    class DummyProcess:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: DummyProcess())
    monkeypatch.setattr(WindsurfExtractor, "_reserve_local_port", lambda self: 43120)
    monkeypatch.setattr(
        WindsurfExtractor,
        "_wait_for_language_server_port",
        lambda self, process, manager_dir, timeout_seconds: None,
    )
    monkeypatch.setattr(
        WindsurfExtractor,
        "_cleanup_manager_dir",
        lambda self, manager_dir: None,
    )

    decoded, errors = extractor._fetch_workspace_trajectories(
        workspace_id=WORKSPACE_ID,
        session_ids=[ACTIVE_SESSION_ID],
        binary_path=Path(__file__),
        node_binary="node",
    )

    assert decoded == {}
    assert ACTIVE_SESSION_ID in errors
    assert "Timed out waiting for Windsurf language server" in errors[ACTIVE_SESSION_ID]


def test_read_language_server_stderr_preview_returns_placeholder_when_log_missing(
    tmp_path, monkeypatch
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        preview = extractor._read_language_server_stderr_preview(Path(temp_dir))

    assert preview == "<missing>"


def test_cleanup_manager_dir_ignores_windows_style_oserror(tmp_path, monkeypatch, caplog):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )
    manager_dir = tmp_path / "manager"
    manager_dir.mkdir()

    def fake_rmtree(path):
        raise OSError(267, "目录名称无效。")

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    with caplog.at_level("DEBUG", logger="anyspecs.extractors.windsurf"):
        extractor._cleanup_manager_dir(manager_dir)

    assert "Failed to cleanup Windsurf manager dir" in caplog.text


def test_cleanup_manager_dir_ignores_permission_error(tmp_path, monkeypatch):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )
    manager_dir = tmp_path / "manager"
    manager_dir.mkdir()

    monkeypatch.setattr(
        shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(PermissionError("busy")),
    )

    extractor._cleanup_manager_dir(manager_dir)


def test_cleanup_manager_dir_removes_existing_directory(tmp_path, monkeypatch):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )
    manager_dir = tmp_path / "manager"
    (manager_dir / "nested").mkdir(parents=True)
    (manager_dir / "nested" / "file.txt").write_text("fixture", encoding="utf-8")

    extractor._cleanup_manager_dir(manager_dir)

    assert not manager_dir.exists()


def test_fetch_workspace_trajectories_still_returns_timeout_when_cleanup_fails(
    tmp_path, monkeypatch
):
    extractor = make_extractor(
        copy_fixture_storage(tmp_path),
        tmp_path / "workspace" / "demo-learning-platform",
        monkeypatch,
    )
    extractor.extension_bundle_path = Path(__file__)
    manager_dir = tmp_path / "fixed-manager-dir"
    manager_dir.mkdir()

    class DummyProcess:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(manager_dir))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: DummyProcess())
    monkeypatch.setattr(WindsurfExtractor, "_reserve_local_port", lambda self: 43120)
    monkeypatch.setattr(
        WindsurfExtractor,
        "_wait_for_language_server_port",
        lambda self, process, manager_dir, timeout_seconds: None,
    )
    monkeypatch.setattr(
        shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError(267, "目录名称无效。")),
    )

    decoded, errors = extractor._fetch_workspace_trajectories(
        workspace_id=WORKSPACE_ID,
        session_ids=[ACTIVE_SESSION_ID],
        binary_path=Path(__file__),
        node_binary="node",
    )

    assert decoded == {}
    assert ACTIVE_SESSION_ID in errors
    assert "Timed out waiting for Windsurf language server" in errors[ACTIVE_SESSION_ID]
