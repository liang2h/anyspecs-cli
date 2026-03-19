from anyspecs.cli import AnySpecsCLI


class FakeCodexExtractor:
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
