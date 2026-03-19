import json
from pathlib import Path

import pytest

from anyspecs.cli import AnySpecsCLI
from anyspecs.utils.uploader import AnySpecsUploadClient


class RecordingClient:
    DEFAULT_BASE_URL = "https://hub.anyspecs.cn/"
    instances = []

    def __init__(self, base_url=DEFAULT_BASE_URL, token=None, use_http=False):
        self.base_url = base_url
        self.token = token
        self.use_http = use_http
        self.calls = []
        RecordingClient.instances.append(self)

    def validate_token(self):
        self.calls.append(("validate_token",))
        return True

    def upload_file(self, file_path, description=""):
        self.calls.append(("upload_file", file_path, description))
        return True

    def upload_directory_anyspecs(self, directory, description=""):
        self.calls.append(("upload_directory_anyspecs", directory, description))
        return {"success": 2, "failed": 0, "skipped": 0}

    def upload_exported_file(
        self,
        file_path,
        metadata=None,
        description="",
        username="",
        oss_config=None,
    ):
        self.calls.append(
            ("upload_exported_file", file_path, metadata, description, username, oss_config)
        )
        return True

    def upload_directory_oss(
        self,
        directory,
        description="",
        username="",
        oss_config=None,
    ):
        self.calls.append(
            ("upload_directory_oss", directory, description, username, oss_config)
        )
        return {"success": 1, "failed": 0, "skipped": 1}

    def list_files(self, page=0, search=""):
        self.calls.append(("list_files", page, search))
        return True


def reset_recording_client():
    RecordingClient.instances = []


def test_upload_parser_rejects_file_and_dir_together():
    cli = AnySpecsCLI()
    parser = cli._create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["upload", "--file", "a.txt", "--dir"])


def test_anyspecs_upload_uses_cli_url_before_env(tmp_path, monkeypatch):
    reset_recording_client()
    upload_file = tmp_path / "demo.txt"
    upload_file.write_text("hello", encoding="utf-8")

    monkeypatch.setenv("ANYSPECS_TOKEN", "env-token")
    monkeypatch.setenv("ANYSPECS_UPLOAD_URL", "https://env.example")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient", RecordingClient)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        [
            "upload",
            "--hub-type",
            "anyspecs",
            "--url",
            "https://cli.example",
            "--file",
            str(upload_file),
        ]
    )

    assert exit_code == 0
    client = RecordingClient.instances[0]
    assert client.base_url == "https://cli.example"
    assert client.token == "env-token"
    assert ("validate_token",) in client.calls
    assert ("upload_file", str(upload_file), "") in client.calls


def test_anyspecs_upload_uses_config_when_env_missing(tmp_path, monkeypatch):
    reset_recording_client()
    upload_file = tmp_path / "demo.txt"
    upload_file.write_text("hello", encoding="utf-8")

    monkeypatch.delenv("ANYSPECS_TOKEN", raising=False)
    monkeypatch.delenv("ANYSPECS_UPLOAD_URL", raising=False)
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient", RecordingClient)

    values = {
        "upload.anyspecs.server_url": "https://config.example",
        "upload.anyspecs.token": "config-token",
    }
    monkeypatch.setattr("anyspecs.cli.config.get", lambda key, default=None: values.get(key, default))

    cli = AnySpecsCLI()
    exit_code = cli.run(["upload", "--hub-type", "anyspecs", "--file", str(upload_file)])

    assert exit_code == 0
    client = RecordingClient.instances[0]
    assert client.base_url == "https://config.example"
    assert client.token == "config-token"


def test_anyspecs_dir_without_path_defaults_to_dot_anyspecs(monkeypatch):
    reset_recording_client()
    monkeypatch.setenv("ANYSPECS_TOKEN", "env-token")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient", RecordingClient)

    cli = AnySpecsCLI()
    exit_code = cli.run(["upload", "--hub-type", "anyspecs", "--dir"])

    assert exit_code == 0
    client = RecordingClient.instances[0]
    assert ("upload_directory_anyspecs", ".anyspecs", "") in client.calls


def test_oss_upload_requires_username(tmp_path, monkeypatch, capsys):
    upload_file = tmp_path / "chat.md"
    upload_file.write_text("hello", encoding="utf-8")

    monkeypatch.delenv("ANYSPECS_UPLOAD_USERNAME", raising=False)
    monkeypatch.setattr("anyspecs.cli.config.get", lambda key, default=None: None)

    cli = AnySpecsCLI()
    exit_code = cli.run(["upload", "--hub-type", "oss", "--file", str(upload_file)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "ANYSPECS_UPLOAD_USERNAME" in output


def test_oss_upload_ignores_url_and_token_and_uses_username(tmp_path, monkeypatch):
    reset_recording_client()
    upload_file = tmp_path / "chat.md"
    upload_file.write_text("hello", encoding="utf-8")
    (tmp_path / "chat.md.meta.json").write_text(
        json.dumps(
            {
                "source": "codex",
                "session_id": "abc123",
                "format": "markdown",
                "chat_date": "2026/03/19",
                "dedupe_key": "codex:abc123:markdown",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANYSPECS_UPLOAD_USERNAME", "liang2h")
    monkeypatch.setenv("ANYSPECS_TOKEN", "ignored-token")
    monkeypatch.setenv("ANYSPECS_UPLOAD_URL", "https://ignored.example")
    monkeypatch.setenv("OSS_BUCKET", "demo-bucket")
    monkeypatch.setenv("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "key-secret")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient", RecordingClient)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        [
            "upload",
            "--hub-type",
            "oss",
            "--url",
            "https://ignored-cli.example",
            "--file",
            str(upload_file),
        ]
    )

    assert exit_code == 0
    client = RecordingClient.instances[0]
    assert client.base_url == RecordingClient.DEFAULT_BASE_URL
    assert client.token is None
    assert ("validate_token",) not in client.calls
    assert (
        "upload_exported_file",
        str(upload_file),
        None,
        "",
        "liang2h",
        {
            "bucket": "demo-bucket",
            "endpoint": "oss-cn-hangzhou.aliyuncs.com",
            "region": None,
            "access_key_id": "key-id",
            "access_key_secret": "key-secret",
            "public_base_url": None,
        },
    ) in client.calls


def test_oss_directory_upload_only_processes_files_with_sidecars(tmp_path, monkeypatch):
    export_dir = tmp_path / ".anyspecs"
    export_dir.mkdir()
    good_file = export_dir / "chat.md"
    good_file.write_text("chat", encoding="utf-8")
    (export_dir / "chat.md.meta.json").write_text(
        json.dumps(
            {
                "source": "claude",
                "session_id": "session-1",
                "format": "markdown",
                "chat_date": "2026/03/19",
                "dedupe_key": "claude:session-1:markdown",
            }
        ),
        encoding="utf-8",
    )
    (export_dir / "orphan.md").write_text("orphan", encoding="utf-8")

    client = AnySpecsUploadClient()
    uploaded = []

    def fake_upload(file_path, metadata=None, description="", username="", oss_config=None):
        uploaded.append((file_path, metadata, description, username, oss_config))
        return True

    monkeypatch.setattr(client, "upload_exported_file", fake_upload)

    summary = client.upload_directory_oss(
        str(export_dir),
        description="desc",
        username="liang2h",
        oss_config={"bucket": "demo-bucket"},
    )

    assert summary == {"success": 1, "failed": 0, "skipped": 2}
    assert uploaded == [
        (
            str(good_file),
            {
                "source": "claude",
                "session_id": "session-1",
                "format": "markdown",
                "chat_date": "2026/03/19",
                "dedupe_key": "claude:session-1:markdown",
            },
            "desc",
            "liang2h",
            {"bucket": "demo-bucket"},
        )
    ]


def test_oss_upload_requires_bucket_configuration(tmp_path, monkeypatch, capsys):
    upload_file = tmp_path / "chat.md"
    upload_file.write_text("hello", encoding="utf-8")
    (tmp_path / "chat.md.meta.json").write_text(
        json.dumps(
            {
                "source": "codex",
                "session_id": "abc123",
                "format": "markdown",
                "chat_date": "2026/03/19",
                "dedupe_key": "codex:abc123:markdown",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANYSPECS_UPLOAD_USERNAME", "liang2h")
    monkeypatch.delenv("OSS_BUCKET", raising=False)
    monkeypatch.delenv("OSS_ENDPOINT", raising=False)
    monkeypatch.delenv("OSS_REGION", raising=False)
    monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.setattr("anyspecs.cli.config.get", lambda key, default=None: None)

    cli = AnySpecsCLI()
    exit_code = cli.run(["upload", "--hub-type", "oss", "--file", str(upload_file)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Missing OSS configuration" in output
    assert "OSS_BUCKET" in output


def test_upload_exported_file_to_oss_uses_object_key_and_headers(tmp_path, monkeypatch):
    export_file = tmp_path / "chat.md"
    export_file.write_text("hello", encoding="utf-8")

    bucket_calls = []

    class FakeBucket:
        bucket_name = "demo-bucket"

        def put_object_from_file(self, key, filename, headers=None, progress_callback=None):
            bucket_calls.append((key, filename, headers, progress_callback))

    monkeypatch.setattr(
        AnySpecsUploadClient,
        "_create_oss_bucket",
        staticmethod(lambda oss_config: FakeBucket()),
    )

    client = AnySpecsUploadClient()
    ok = client.upload_exported_file(
        str(export_file),
        metadata={
            "source": "claude",
            "session_id": "session-1",
            "format": "markdown",
            "chat_date": "2026/03/19",
            "dedupe_key": "claude:session-1:markdown",
        },
        description="demo",
        username="liang2h",
        oss_config={
            "bucket": "demo-bucket",
            "endpoint": "oss-cn-hangzhou.aliyuncs.com",
            "access_key_id": "key-id",
            "access_key_secret": "key-secret",
        },
    )

    assert ok is True
    assert bucket_calls == [
        (
            "liang2h/2026/03/19/chat.md",
            str(export_file),
            {
                "x-oss-meta-source": "claude",
                "x-oss-meta-session-id": "session-1",
                "x-oss-meta-format": "markdown",
                "x-oss-meta-chat-date": "2026/03/19",
                "x-oss-meta-dedupe-key": "claude:session-1:markdown",
                "x-oss-meta-description": "demo",
                "Content-Type": "text/markdown",
            },
            None,
        )
    ]


def test_create_oss_bucket_builds_endpoint_from_region():
    bucket = AnySpecsUploadClient._create_oss_bucket

    class FakeAuth:
        def __init__(self, key_id, key_secret):
            self.key_id = key_id
            self.key_secret = key_secret

    class FakeBucket:
        def __init__(self, auth, endpoint, bucket_name):
            self.auth = auth
            self.endpoint = endpoint
            self.bucket_name = bucket_name

    import types

    fake_oss2 = types.SimpleNamespace(Auth=FakeAuth, Bucket=FakeBucket)
    import sys
    previous = sys.modules.get("oss2")
    sys.modules["oss2"] = fake_oss2
    try:
        created = bucket(
            {
                "bucket": "demo-bucket",
                "region": "cn-hangzhou",
                "access_key_id": "key-id",
                "access_key_secret": "key-secret",
            }
        )
    finally:
        if previous is None:
            del sys.modules["oss2"]
        else:
            sys.modules["oss2"] = previous

    assert created.bucket_name == "demo-bucket"
    assert created.endpoint == "https://oss-cn-hangzhou.aliyuncs.com"
    assert created.auth.key_id == "key-id"


def test_export_multiple_writes_stable_filename_and_sidecar(tmp_path):
    cli = AnySpecsCLI()
    formatter = cli.formatters["markdown"]
    args = type("Args", (), {"output": tmp_path})()
    chat = {
        "project": {"name": "demo-app", "rootPath": "/tmp/demo-app"},
        "messages": [{"role": "user", "content": "hello"}],
        "date": 1773878400,
        "session_id": "session-12345678",
        "source": "codex",
        "metadata": {},
    }

    first = cli._export_multiple_chats([chat], formatter, args)
    second = cli._export_multiple_chats([chat], formatter, args)

    assert first == 0
    assert second == 0

    export_file = tmp_path / "codex-chat-demo-app-session-.md"
    metadata_file = tmp_path / "codex-chat-demo-app-session-.md.meta.json"
    assert export_file.exists()
    assert metadata_file.exists()

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["source"] == "codex"
    assert metadata["session_id"] == "session-12345678"
    assert metadata["format"] == "markdown"
    assert metadata["dedupe_key"] == "codex:session-12345678:markdown"
    assert metadata["chat_date"] == "2026/03/19"
    assert len(list(tmp_path.glob("*.md"))) == 1
