import datetime as real_datetime
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

    def upload_directory_anyspecs(self, directory, description="", on_success=None):
        self.calls.append(("upload_directory_anyspecs", directory, description))
        return {"success": 2, "failed": 0, "skipped": 0}

    def upload_exported_file(
        self,
        file_path,
        metadata=None,
        description="",
        username="",
        oss_config=None,
        date_format="yyyy-mm-dd",
    ):
        self.calls.append(
            (
                "upload_exported_file",
                file_path,
                metadata,
                description,
                username,
                oss_config,
                date_format,
            )
        )
        return True

    def upload_directory_oss(
        self,
        directory,
        description="",
        username="",
        oss_config=None,
        date_format="yyyy-mm-dd",
        on_success=None,
    ):
        self.calls.append(
            (
                "upload_directory_oss",
                directory,
                description,
                username,
                oss_config,
                date_format,
            )
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


def test_upload_parser_defaults_date_format_to_yyyy_mm_dd():
    cli = AnySpecsCLI()
    parser = cli._create_parser()

    args = parser.parse_args(["upload", "--hub-type", "oss", "--file", "a.txt"])

    assert args.date_format == "yyyy-mm-dd"


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


def test_anyspecs_upload_file_rm_deletes_file_and_sidecar(tmp_path, monkeypatch):
    upload_file = tmp_path / "demo.txt"
    upload_file.write_text("hello", encoding="utf-8")
    sidecar = tmp_path / "demo.txt.meta.json"
    sidecar.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ANYSPECS_TOKEN", "env-token")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient.validate_token", lambda self: True)
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient.upload_file", lambda self, file_path, description="": True)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        ["upload", "--hub-type", "anyspecs", "--file", str(upload_file), "--rm"]
    )

    assert exit_code == 0
    assert not upload_file.exists()
    assert not sidecar.exists()


def test_anyspecs_upload_dir_rm_only_deletes_successful_uploads(tmp_path, monkeypatch):
    upload_dir = tmp_path / ".anyspecs"
    upload_dir.mkdir()
    ok_file = upload_dir / "ok.md"
    ok_file.write_text("ok", encoding="utf-8")
    ok_sidecar = upload_dir / "ok.md.meta.json"
    ok_sidecar.write_text("{}", encoding="utf-8")
    failed_file = upload_dir / "failed.md"
    failed_file.write_text("failed", encoding="utf-8")

    def fake_upload(self, file_path, description=""):
        return Path(file_path).name != "failed.md"

    monkeypatch.setenv("ANYSPECS_TOKEN", "env-token")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient.validate_token", lambda self: True)
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient.upload_file", fake_upload)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        ["upload", "--hub-type", "anyspecs", "--dir", str(upload_dir), "--rm"]
    )

    assert exit_code == 0
    assert not ok_file.exists()
    assert not ok_sidecar.exists()
    assert failed_file.exists()


def test_anyspecs_upload_search_ignores_rm(monkeypatch):
    reset_recording_client()
    monkeypatch.setenv("ANYSPECS_TOKEN", "env-token")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient", RecordingClient)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        ["upload", "--hub-type", "anyspecs", "--search", "demo", "--rm"]
    )

    assert exit_code == 0
    client = RecordingClient.instances[0]
    assert ("list_files", 0, "demo") in client.calls


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
        "yyyy-mm-dd",
    ) in client.calls


def test_oss_upload_dir_passes_explicit_date_format(monkeypatch):
    reset_recording_client()
    monkeypatch.setenv("ANYSPECS_UPLOAD_USERNAME", "liang2h")
    monkeypatch.setenv("OSS_BUCKET", "demo-bucket")
    monkeypatch.setenv("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "key-secret")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient", RecordingClient)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        ["upload", "--hub-type", "oss", "--dir", "--date-format", "yyyy/mm/dd"]
    )

    assert exit_code == 0
    client = RecordingClient.instances[0]
    assert (
        "upload_directory_oss",
        ".anyspecs",
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
        "yyyy/mm/dd",
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

    def fake_upload(
        file_path,
        metadata=None,
        description="",
        username="",
        oss_config=None,
        date_format="yyyy-mm-dd",
    ):
        uploaded.append((file_path, metadata, description, username, oss_config, date_format))
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
            "yyyy-mm-dd",
        )
    ]


def test_oss_upload_file_rm_deletes_file_and_sidecar(tmp_path, monkeypatch):
    upload_file = tmp_path / "chat.md"
    upload_file.write_text("hello", encoding="utf-8")
    sidecar = tmp_path / "chat.md.meta.json"
    sidecar.write_text(
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
    monkeypatch.setenv("OSS_BUCKET", "demo-bucket")
    monkeypatch.setenv("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "key-secret")
    monkeypatch.setattr(
        "anyspecs.cli.AnySpecsUploadClient.upload_exported_file",
        lambda self, file_path, metadata=None, description="", username="", oss_config=None, date_format="yyyy-mm-dd": True,
    )

    cli = AnySpecsCLI()
    exit_code = cli.run(["upload", "--hub-type", "oss", "--file", str(upload_file), "--rm"])

    assert exit_code == 0
    assert not upload_file.exists()
    assert not sidecar.exists()


def test_oss_upload_dir_rm_deletes_uploaded_exports_only(tmp_path, monkeypatch):
    upload_dir = tmp_path / ".anyspecs"
    upload_dir.mkdir()
    good_file = upload_dir / "good.md"
    good_file.write_text("good", encoding="utf-8")
    good_sidecar = upload_dir / "good.md.meta.json"
    good_sidecar.write_text(
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
    orphan_file = upload_dir / "orphan.md"
    orphan_file.write_text("orphan", encoding="utf-8")
    bare_sidecar = upload_dir / "bare.meta.json"
    bare_sidecar.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ANYSPECS_UPLOAD_USERNAME", "liang2h")
    monkeypatch.setenv("OSS_BUCKET", "demo-bucket")
    monkeypatch.setenv("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "key-secret")
    monkeypatch.setattr(
        "anyspecs.cli.AnySpecsUploadClient.upload_exported_file",
        lambda self, file_path, metadata=None, description="", username="", oss_config=None, date_format="yyyy-mm-dd": True,
    )

    cli = AnySpecsCLI()
    exit_code = cli.run(["upload", "--hub-type", "oss", "--dir", str(upload_dir), "--rm"])

    assert exit_code == 0
    assert not good_file.exists()
    assert not good_sidecar.exists()
    assert orphan_file.exists()
    assert bare_sidecar.exists()


def test_upload_rm_warns_on_cleanup_failure_but_keeps_success_exit_code(tmp_path, monkeypatch, capsys):
    upload_file = tmp_path / "demo.txt"
    upload_file.write_text("hello", encoding="utf-8")
    sidecar = tmp_path / "demo.txt.meta.json"
    sidecar.write_text("{}", encoding="utf-8")
    original_unlink = Path.unlink

    def fake_unlink(self, *args, **kwargs):
        if self == upload_file:
            raise PermissionError("denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setenv("ANYSPECS_TOKEN", "env-token")
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient.validate_token", lambda self: True)
    monkeypatch.setattr("anyspecs.cli.AnySpecsUploadClient.upload_file", lambda self, file_path, description="": True)
    monkeypatch.setattr(Path, "unlink", fake_unlink)

    cli = AnySpecsCLI()
    exit_code = cli.run(
        ["upload", "--hub-type", "anyspecs", "--file", str(upload_file), "--rm"]
    )

    assert exit_code == 0
    assert upload_file.exists()
    assert not sidecar.exists()
    assert "Failed to remove local file after upload" in capsys.readouterr().out


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
            "liang2h/2026-03-19/chat.md",
            str(export_file),
            {
                "x-oss-meta-source": "claude",
                "x-oss-meta-session-id": "session-1",
                "x-oss-meta-format": "markdown",
                "x-oss-meta-chat-date": "2026-03-19",
                "x-oss-meta-dedupe-key": "claude:session-1:markdown",
                "x-oss-meta-description": "demo",
                "Content-Type": "text/markdown",
            },
            None,
        )
    ]


def test_upload_exported_file_to_oss_supports_slash_date_format(tmp_path, monkeypatch):
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
            "chat_date": "2026-03-19",
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
        date_format="yyyy/mm/dd",
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


def test_upload_exported_file_to_oss_falls_back_to_current_utc_date(tmp_path, monkeypatch):
    export_file = tmp_path / "chat.md"
    export_file.write_text("hello", encoding="utf-8")

    bucket_calls = []

    class FakeBucket:
        bucket_name = "demo-bucket"

        def put_object_from_file(self, key, filename, headers=None, progress_callback=None):
            bucket_calls.append((key, filename, headers, progress_callback))

    class FixedDateTime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.datetime(2026, 3, 20, 9, 0, tzinfo=tz)

    monkeypatch.setattr(
        AnySpecsUploadClient,
        "_create_oss_bucket",
        staticmethod(lambda oss_config: FakeBucket()),
    )
    monkeypatch.setattr("anyspecs.utils.uploader.datetime", FixedDateTime)

    client = AnySpecsUploadClient()
    ok = client.upload_exported_file(
        str(export_file),
        metadata={
            "source": "claude",
            "session_id": "session-1",
            "format": "markdown",
            "chat_date": "not-a-date",
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
            "liang2h/2026-03-20/chat.md",
            str(export_file),
            {
                "x-oss-meta-source": "claude",
                "x-oss-meta-session-id": "session-1",
                "x-oss-meta-format": "markdown",
                "x-oss-meta-chat-date": "2026-03-20",
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
    export_file = tmp_path / "codex-chat-demo-app-session-12345678.md"
    first_content = export_file.read_text(encoding="utf-8")
    second = cli._export_multiple_chats([chat], formatter, args)
    second_content = export_file.read_text(encoding="utf-8")

    assert first == 0
    assert second == 0

    metadata_file = tmp_path / "codex-chat-demo-app-session-12345678.md.meta.json"
    assert export_file.exists()
    assert metadata_file.exists()

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert "Exported from codex" in first_content
    assert "Exported from codex on " not in first_content
    assert "Exported from codex" in second_content
    assert "Exported from codex on " not in second_content
    assert first_content == second_content
    assert first_content.rstrip().splitlines()[-1] == "*Exported from codex*"
    assert metadata["source"] == "codex"
    assert metadata["session_id"] == "session-12345678"
    assert metadata["format"] == "markdown"
    assert metadata["dedupe_key"] == "codex:session-12345678:markdown"
    assert metadata["chat_date"] == "2026/03/19"
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_export_html_keeps_static_footer_without_dynamic_time(tmp_path):
    cli = AnySpecsCLI()
    formatter = cli.formatters["html"]
    args = type("Args", (), {"output": tmp_path})()
    chat = {
        "project": {"name": "demo-app", "rootPath": "/tmp/demo-app"},
        "messages": [{"role": "assistant", "content": "hello <world>"}],
        "date": 1773878400,
        "session_id": "session-html-123",
        "source": "codex",
        "metadata": {},
    }

    result = cli._export_multiple_chats([chat], formatter, args)

    assert result == 0

    export_file = tmp_path / "codex-chat-demo-app-session-html-123.html"
    assert export_file.exists()

    content = export_file.read_text(encoding="utf-8")
    assert "Exported from codex" in content
    assert "Exported from codex on " not in content
    assert "Chat Export: demo-app" in content
    assert "Session ID:</span> <span>session-html-123" in content
    assert "Source:</span> <span>codex" in content
    assert "hello &lt;world&gt;" in content


def test_build_export_filename_stem_sanitizes_invalid_windows_path_characters():
    cli = AnySpecsCLI()
    chat = {
        "project": {"name": r"C:\Users\15257\Desktop\jzx-devops-all"},
        "session_id": r"019d0937-0318-7381-99ee-d367e372c34c",
        "source": "codex",
    }

    filename_stem = cli._build_export_filename_stem(chat)

    assert filename_stem == (
        "codex-chat-C_Users_15257_Desktop_jzx-devops-all-"
        "019d0937-0318-7381-99ee-d367e372c34c"
    )
    assert ":" not in filename_stem
    assert "\\" not in filename_stem
    assert "/" not in filename_stem


def test_export_multiple_with_windows_style_project_name_writes_file(tmp_path):
    cli = AnySpecsCLI()
    formatter = cli.formatters["markdown"]
    args = type("Args", (), {"output": tmp_path})()
    chat = {
        "project": {"name": r"C:\Users\15257\Desktop\jzx-devops-all"},
        "messages": [{"role": "user", "content": "hello"}],
        "date": 1773878400,
        "session_id": "019d0937-0318-7381-99ee-d367e372c34c",
        "source": "codex",
        "metadata": {},
    }

    result = cli._export_multiple_chats([chat], formatter, args)

    assert result == 0
    export_file = (
        tmp_path
        / "codex-chat-C_Users_15257_Desktop_jzx-devops-all-019d0937-0318-7381-99ee-d367e372c34c.md"
    )
    metadata_file = export_file.with_name(f"{export_file.name}.meta.json")
    assert export_file.exists()
    assert metadata_file.exists()


def test_export_now_filters_to_today_before_limit(monkeypatch):
    class FixedDateTime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return real_datetime.datetime(2026, 3, 20, 9, 0, tzinfo=tz)
            return cls(2026, 3, 20, 9, 0)

    monkeypatch.setattr("anyspecs.cli.datetime.datetime", FixedDateTime)

    cli = AnySpecsCLI()
    args = type(
        "Args",
        (),
        {
            "session_id": None,
            "project": None,
            "all_projects": True,
            "limit": 1,
            "now": True,
        },
    )()
    chats = [
        {"session_id": "yesterday", "project": {"name": "demo"}, "date": "2026-03-19T23:59:59"},
        {"session_id": "today-1", "project": {"name": "demo"}, "date": "2026-03-20T00:00:00"},
        {"session_id": "today-2", "project": {"name": "demo"}, "date": "2026-03-20T12:30:00"},
    ]

    filtered = cli._apply_filters(chats, args)

    assert [chat["session_id"] for chat in filtered] == ["today-1"]


def test_export_now_excludes_unparseable_dates(monkeypatch):
    class FixedDateTime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return real_datetime.datetime(2026, 3, 20, 9, 0, tzinfo=tz)
            return cls(2026, 3, 20, 9, 0)

    monkeypatch.setattr("anyspecs.cli.datetime.datetime", FixedDateTime)

    cli = AnySpecsCLI()
    cli.logger = type("Logger", (), {"debug": lambda *args, **kwargs: None})()
    args = type(
        "Args",
        (),
        {
            "session_id": None,
            "project": None,
            "all_projects": True,
            "limit": None,
            "now": True,
        },
    )()
    chats = [
        {"session_id": "bad", "project": {"name": "demo"}, "date": "not-a-date"},
        {"session_id": "good", "project": {"name": "demo"}, "date": "2026-03-20T08:00:00+08:00"},
    ]

    filtered = cli._apply_filters(chats, args)

    assert [chat["session_id"] for chat in filtered] == ["good"]


def test_export_without_now_keeps_existing_filter_behavior():
    cli = AnySpecsCLI()
    args = type(
        "Args",
        (),
        {
            "session_id": None,
            "project": None,
            "all_projects": True,
            "limit": None,
            "now": False,
        },
    )()
    chats = [
        {"session_id": "bad", "project": {"name": "demo"}, "date": "not-a-date"},
        {"session_id": "good", "project": {"name": "demo"}, "date": 1773878400},
    ]

    filtered = cli._apply_filters(chats, args)

    assert [chat["session_id"] for chat in filtered] == ["bad", "good"]
