import copy
import json
import shutil
import subprocess
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
    assert by_id["f32adc43"]["preview"] == "梳理一下核心数据模型"
    assert by_id["f32adc43"]["message_count"] == 3
    expected_date = datetime.fromtimestamp(1774347887599 / 1000).strftime("%Y-%m-%d %H:%M")
    assert by_id["cbc99144"]["date"] == expected_date


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
