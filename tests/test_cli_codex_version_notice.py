from anyspecs.cli import AnySpecsCLI


class FakeCodexExtractor:
    def __init__(self, info):
        self._info = info

    def get_version_support_info(self):
        return self._info


class FakeClaudeExtractor:
    def __init__(self, info):
        self._info = info

    def get_version_support_info(self):
        return self._info


def test_prints_codex_version_notice_for_codex_source(capsys):
    cli = AnySpecsCLI()
    cli.extractors["codex"] = FakeCodexExtractor(
        {
            "supported_versions": [
                "0.106.0",
                "0.111.0",
                "0.114.0",
                "0.115.0-alpha.27",
            ],
            "detected_versions": ["0.114.0", "0.115.0-alpha.28"],
            "unsupported_versions": ["0.115.0-alpha.28"],
            "has_sessions": True,
        }
    )

    cli._print_codex_version_notice(["codex"])
    output = capsys.readouterr().out

    assert "Codex 已验证支持版本" in output
    assert "0.106.0, 0.111.0, 0.114.0, 0.115.0-alpha.27" in output
    assert "本机检测到的 Codex 版本" in output
    assert "0.114.0, 0.115.0-alpha.28" in output
    assert "未验证的 Codex 版本" in output


def test_prints_codex_version_notice_once_for_all_source(capsys):
    cli = AnySpecsCLI()
    cli.extractors["codex"] = FakeCodexExtractor(
        {
            "supported_versions": ["0.114.0"],
            "detected_versions": ["0.114.0"],
            "unsupported_versions": [],
            "has_sessions": True,
        }
    )

    cli._print_codex_version_notice(["cursor", "codex", "claude"])
    output = capsys.readouterr().out

    assert output.count("Codex 已验证支持版本") == 1
    assert output.count("本机检测到的 Codex 版本") == 1


def test_does_not_print_codex_notice_when_codex_not_requested(capsys):
    cli = AnySpecsCLI()
    cli.extractors["codex"] = FakeCodexExtractor(
        {
            "supported_versions": ["0.114.0"],
            "detected_versions": ["0.114.0"],
            "unsupported_versions": [],
            "has_sessions": True,
        }
    )

    cli._print_codex_version_notice(["cursor", "claude"])
    output = capsys.readouterr().out

    assert output == ""


def test_prints_claude_version_notice_for_claude_source(capsys):
    cli = AnySpecsCLI()
    cli.extractors["claude"] = FakeClaudeExtractor(
        {
            "supported_versions": [
                "1.0.98",
                "2.1.59",
                "2.1.62",
                "2.1.63",
                "2.1.71",
                "2.1.72",
            ],
            "detected_versions": ["2.1.71", "2.1.73"],
            "unsupported_versions": ["2.1.73"],
            "has_sessions": True,
        }
    )

    cli._print_claude_version_notice(["claude"])
    output = capsys.readouterr().out

    assert "Claude 已验证支持版本" in output
    assert "1.0.98, 2.1.59, 2.1.62, 2.1.63, 2.1.71, 2.1.72" in output
    assert "本机检测到的 Claude 版本" in output
    assert "2.1.71, 2.1.73" in output
    assert "未验证的 Claude 版本" in output


def test_prints_claude_version_notice_once_for_all_source(capsys):
    cli = AnySpecsCLI()
    cli.extractors["claude"] = FakeClaudeExtractor(
        {
            "supported_versions": ["2.1.71"],
            "detected_versions": ["2.1.71"],
            "unsupported_versions": [],
            "has_sessions": True,
        }
    )

    cli._print_claude_version_notice(["cursor", "claude", "codex"])
    output = capsys.readouterr().out

    assert output.count("Claude 已验证支持版本") == 1
    assert output.count("本机检测到的 Claude 版本") == 1


def test_does_not_print_claude_notice_when_claude_not_requested(capsys):
    cli = AnySpecsCLI()
    cli.extractors["claude"] = FakeClaudeExtractor(
        {
            "supported_versions": ["2.1.71"],
            "detected_versions": ["2.1.71"],
            "unsupported_versions": [],
            "has_sessions": True,
        }
    )

    cli._print_claude_version_notice(["cursor", "codex"])
    output = capsys.readouterr().out

    assert output == ""
