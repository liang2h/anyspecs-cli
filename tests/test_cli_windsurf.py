import json
from pathlib import Path

from anyspecs.cli import AnySpecsCLI


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "windsurf" / "storage"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def test_export_command_writes_windsurf_markdown_and_sidecar(tmp_path, monkeypatch):
    project_dir = tmp_path / "workspace" / "demo-learning-platform"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(project_dir)

    cli = AnySpecsCLI()
    cli.logger = DummyLogger()
    cli.extractors["windsurf"].app_root = FIXTURE_ROOT / "app"
    cli.extractors["windsurf"].storage_root = FIXTURE_ROOT / "codeium"

    args = type(
        "Args",
        (),
        {
            "source": "windsurf",
            "format": "markdown",
            "output": tmp_path,
            "session_id": None,
            "project": None,
            "all_projects": True,
            "limit": None,
            "now": False,
            "verbose": False,
        },
    )()

    result = cli._export_command(args)

    assert result == 0
    export_file = (
        tmp_path
        / "windsurf-chat-demo-learning-platform-cbc99144-4e48-4e68-89f7-3f1608611bbe.md"
    )
    metadata_file = export_file.with_name(f"{export_file.name}.meta.json")

    assert export_file.exists()
    assert metadata_file.exists()

    content = export_file.read_text(encoding="utf-8")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

    assert "介绍下项目概况" in content
    assert "# 项目概况" in content
    assert metadata["source"] == "windsurf"
    assert metadata["session_id"] == "cbc99144-4e48-4e68-89f7-3f1608611bbe"
    assert metadata["format"] == "markdown"
    assert metadata["project_name"] == "demo-learning-platform"
    assert (
        metadata["dedupe_key"]
        == "windsurf:cbc99144-4e48-4e68-89f7-3f1608611bbe:markdown"
    )
