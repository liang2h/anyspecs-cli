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
