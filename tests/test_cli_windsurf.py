import json
import shutil
from pathlib import Path

from anyspecs.cli import AnySpecsCLI
from anyspecs.exporters.windsurf import WindsurfExtractor


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "windsurf" / "storage"
ACTIVE_SESSION_ID = "cbc99144-4e48-4e68-89f7-3f1608611bbe"
HISTORICAL_SESSION_ID = "f32adc43-5d83-41e5-ab27-736a817cf70d"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


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


def make_cli(tmp_path, monkeypatch) -> AnySpecsCLI:
    storage_base = copy_fixture_storage(tmp_path)
    project_dir = tmp_path / "workspace" / "demo-learning-platform"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(project_dir)

    cli = AnySpecsCLI()
    cli.logger = DummyLogger()
    cli.extractors["windsurf"].app_root = storage_base / "app"
    cli.extractors["windsurf"].storage_root = storage_base / "codeium"
    cli.extractors["windsurf"].extension_bundle_path = Path(__file__)
    return cli


def make_args(tmp_path, **overrides):
    args = {
        "source": "windsurf",
        "format": "markdown",
        "output": tmp_path,
        "session_id": None,
        "project": None,
        "all_projects": True,
        "limit": None,
        "now": False,
        "verbose": False,
    }
    args.update(overrides)
    return type("Args", (), args)()


def test_export_command_can_export_non_active_historical_session(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    cli = make_cli(tmp_path, monkeypatch)

    result = cli._export_command(
        make_args(tmp_path, session_id=HISTORICAL_SESSION_ID[:8])
    )

    assert result == 0
    export_file = (
        tmp_path
        / "windsurf-chat-demo-learning-platform-f32adc43-5d83-41e5-ab27-736a817cf70d.md"
    )
    metadata_file = export_file.with_name(f"{export_file.name}.meta.json")

    assert export_file.exists()
    assert metadata_file.exists()

    content = export_file.read_text(encoding="utf-8")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

    assert "梳理一下核心数据模型" in content
    assert "核心数据模型" in content
    assert metadata["source"] == "windsurf"
    assert metadata["session_id"] == HISTORICAL_SESSION_ID
    assert metadata["project_name"] == "demo-learning-platform"


def test_export_command_only_decodes_requested_windsurf_session(tmp_path, monkeypatch):
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
            if decoded_path.exists():
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

    cli = make_cli(tmp_path, monkeypatch)

    result = cli._export_command(
        make_args(tmp_path, session_id=HISTORICAL_SESSION_ID[:8])
    )

    assert result == 0
    assert calls == [("359c582b8bf0e42edf8be0b6be435fa6", [HISTORICAL_SESSION_ID])]


def test_export_command_without_session_id_exports_all_matching_windsurf_chats(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    cli = make_cli(tmp_path, monkeypatch)

    result = cli._export_command(make_args(tmp_path))

    assert result == 0
    exported_files = sorted(tmp_path.glob("windsurf-chat-*.md"))
    assert [path.name for path in exported_files] == [
        "windsurf-chat-demo-learning-platform-cbc99144-4e48-4e68-89f7-3f1608611bbe.md",
        "windsurf-chat-demo-learning-platform-f32adc43-5d83-41e5-ab27-736a817cf70d.md",
    ]

    metadata = json.loads(
        exported_files[0].with_name(f"{exported_files[0].name}.meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["session_id"] in {ACTIVE_SESSION_ID, HISTORICAL_SESSION_ID}
    assert metadata["source"] == "windsurf"


def test_list_command_uses_windsurf_index_without_decoding_pb(tmp_path, monkeypatch, capsys):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("list command should not decode pb trajectories")

    monkeypatch.setattr(
        WindsurfExtractor,
        "_fetch_workspace_trajectories",
        fail_if_called,
    )

    cli = make_cli(tmp_path, monkeypatch)
    args = type(
        "Args",
        (),
        {
            "source": "windsurf",
            "verbose": False,
        },
    )()

    result = cli._list_command(args)

    captured = capsys.readouterr()
    assert result == 0
    assert "demo-learning-platform (windsurf)" in captured.out


def test_export_command_source_all_still_filters_windsurf_before_decoding(
    tmp_path, monkeypatch
):
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
            if decoded_path.exists():
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

    cli = make_cli(tmp_path, monkeypatch)
    for source_name, extractor in cli.extractors.items():
        if source_name == "windsurf":
            continue
        extractor.extract_chats = lambda: []

    result = cli._export_command(
        make_args(tmp_path, source="all", session_id=HISTORICAL_SESSION_ID[:8])
    )

    assert result == 0
    assert calls == [("359c582b8bf0e42edf8be0b6be435fa6", [HISTORICAL_SESSION_ID])]


def test_export_command_reuses_same_workspace_server_within_one_command(
    tmp_path, monkeypatch
):
    cli = make_cli(tmp_path, monkeypatch)
    extractor = cli.extractors["windsurf"]

    scope_calls = []
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

    monkeypatch.setattr(
        extractor,
        "begin_command_scope",
        lambda: scope_calls.append("begin")
        or setattr(extractor, "_command_scope_active", True),
    )
    monkeypatch.setattr(
        extractor,
        "close_command_scope",
        lambda: scope_calls.append("close")
        or extractor._workspace_servers.clear()
        or setattr(extractor, "_command_scope_active", False),
    )

    def fake_start_workspace_server(workspace_id, binary_path, node_binary):
        del binary_path, node_binary
        start_calls.append(workspace_id)
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

    monkeypatch.setattr(extractor, "_start_workspace_server", fake_start_workspace_server)
    monkeypatch.setattr(
        extractor,
        "_run_node_json",
        lambda node_binary, script, payload, error_context: {
            "trajectories": {
                session_id: {"sessionId": session_id}
                for session_id in payload["session_ids"]
            },
            "errors": {},
        },
    )
    monkeypatch.setattr(extractor, "_stop_language_server", lambda process: None)
    monkeypatch.setattr(extractor, "_cleanup_manager_dir", lambda manager_dir: None)

    def fake_extract_chats_for_export(session_ids=None, index_context=None):
        del session_ids, index_context
        extractor._fetch_workspace_trajectories(
            workspace_id="359c582b8bf0e42edf8be0b6be435fa6",
            session_ids=[ACTIVE_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
        extractor._fetch_workspace_trajectories(
            workspace_id="359c582b8bf0e42edf8be0b6be435fa6",
            session_ids=[HISTORICAL_SESSION_ID],
            binary_path=Path(__file__),
            node_binary="node",
        )
        return [
            {
                "session_id": ACTIVE_SESSION_ID,
                "project": {"name": "demo-learning-platform", "rootPath": "/tmp/demo"},
                "messages": [{"role": "user", "content": "hello"}],
                "date": 1774347887,
                "metadata": {"storage_kind": "windsurf_pb"},
            }
        ]

    monkeypatch.setattr(extractor, "extract_chats_for_export", fake_extract_chats_for_export)

    result = cli._export_command(make_args(tmp_path, session_id=ACTIVE_SESSION_ID[:8]))

    assert result == 0
    assert start_calls == ["359c582b8bf0e42edf8be0b6be435fa6"]
    assert scope_calls == ["begin", "close"]


def test_export_command_source_all_uses_single_windsurf_command_scope(tmp_path, monkeypatch):
    install_fixture_pb_decoder(monkeypatch)
    cli = make_cli(tmp_path, monkeypatch)
    extractor = cli.extractors["windsurf"]

    scope_calls = []
    monkeypatch.setattr(extractor, "begin_command_scope", lambda: scope_calls.append("begin"))
    monkeypatch.setattr(extractor, "close_command_scope", lambda: scope_calls.append("close"))

    for source_name, other_extractor in cli.extractors.items():
        if source_name == "windsurf":
            continue
        other_extractor.extract_chats = lambda: []

    result = cli._export_command(
        make_args(tmp_path, source="all", session_id=HISTORICAL_SESSION_ID[:8])
    )

    assert result == 0
    assert scope_calls == ["begin", "close"]


def test_export_command_closes_windsurf_scope_when_extraction_errors(
    tmp_path, monkeypatch
):
    cli = make_cli(tmp_path, monkeypatch)
    extractor = cli.extractors["windsurf"]

    scope_calls = []
    monkeypatch.setattr(extractor, "begin_command_scope", lambda: scope_calls.append("begin"))
    monkeypatch.setattr(extractor, "close_command_scope", lambda: scope_calls.append("close"))
    monkeypatch.setattr(
        extractor,
        "build_filter_candidates",
        lambda index_context=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = cli._export_command(make_args(tmp_path))

    assert result == 1
    assert scope_calls == ["begin", "close"]


def test_list_command_wraps_windsurf_in_command_scope(tmp_path, monkeypatch, capsys):
    cli = make_cli(tmp_path, monkeypatch)
    extractor = cli.extractors["windsurf"]

    scope_calls = []
    monkeypatch.setattr(extractor, "begin_command_scope", lambda: scope_calls.append("begin"))
    monkeypatch.setattr(extractor, "close_command_scope", lambda: scope_calls.append("close"))
    monkeypatch.setattr(
        WindsurfExtractor,
        "_fetch_workspace_trajectories",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("list command should not decode pb trajectories")
        ),
    )

    args = type(
        "Args",
        (),
        {
            "source": "windsurf",
            "verbose": False,
        },
    )()

    result = cli._list_command(args)

    captured = capsys.readouterr()
    assert result == 0
    assert "demo-learning-platform (windsurf)" in captured.out
    assert scope_calls == ["begin", "close"]


def test_export_command_errors_when_historical_body_cannot_be_decoded(tmp_path, monkeypatch, capsys):
    install_fixture_pb_decoder(monkeypatch)
    cli = make_cli(tmp_path, monkeypatch)
    windsurf_storage = cli.extractors["windsurf"].storage_root
    (windsurf_storage / "cascade" / f"{HISTORICAL_SESSION_ID}.pb").unlink()
    (windsurf_storage / "decoded" / f"{HISTORICAL_SESSION_ID}.json").unlink()

    result = cli._export_command(
        make_args(tmp_path, session_id=HISTORICAL_SESSION_ID[:8])
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "trajectory body could not be decoded" in captured.out
