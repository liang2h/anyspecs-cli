import json
from pathlib import Path

from anyspecs.cli import AnySpecsCLI


FIXTURE_STORAGE = Path(__file__).resolve().parent / "fixtures" / "opencode" / "storage"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def test_export_command_writes_opencode_markdown_and_sidecar(tmp_path):
    cli = AnySpecsCLI()
    cli.logger = DummyLogger()
    cli.extractors["opencode"].storage_root = FIXTURE_STORAGE

    args = type(
        "Args",
        (),
        {
            "source": "opencode",
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
        / "opencode-chat-sample-app-ses_3f79fd355ffe0mH9k1yc0aO55K.md"
    )
    metadata_file = export_file.with_name(f"{export_file.name}.meta.json")

    assert export_file.exists()
    assert metadata_file.exists()

    content = export_file.read_text(encoding="utf-8")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

    assert "Tool Call: bash" in content
    assert "File Reference: sample/grpc/背景.md" in content
    assert "Patch: fixture-patch-hash-001" in content
    assert "Task ID" in content
    assert metadata["source"] == "opencode"
    assert metadata["session_id"] == "ses_3f79fd355ffe0mH9k1yc0aO55K"
    assert metadata["format"] == "markdown"
    assert metadata["project_name"] == "sample-app"
    assert metadata["dedupe_key"] == "opencode:ses_3f79fd355ffe0mH9k1yc0aO55K:markdown"
