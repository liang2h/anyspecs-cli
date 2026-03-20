<div align="center">

  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/headerDark.svg" />
    <img src="assets/headerLight.svg" alt="AnySpecs CLI" />
  </picture>

***Code is cheap, Show me Any Specs.***
  
[:page_facing_up: 中文版本](https://github.com/anyspecs/anyspecs-cli/blob/main/README_zh.md) |
[:gear: Quick Start](#quick-start) |
[:thinking: Reporting Issues](https://github.com/anyspecs/anyspecs-cli/issues/new/choose)

</div>

AnySpecs CLI is a unified command-line tool for exporting chat history from multiple AI assistants. It currently supports **Cursor AI**, **Claude Code**, **Codex cli**, **Augment** and **Kiro Records**, with support for various export formats including Markdown, HTML, and JSON.

## Features

- **Multi-Source Support**: Export from Cursor AI, Claude Code, Augment Code, Codex cli and Kiro Records(More to come)
- **Multiple Export Formats**: Markdown, HTML, and JSON
- **Project-Based and Workspace Filtering**: Export sessions by project or current directory
- **Flexible Session Management**: List, filter, and export specific sessions
- **Default Export Directory**: All exports save to `.anyspecs/` by default for organized storage
- **Stable Export Files**: Export filenames use the full session ID and generate a `.meta.json` sidecar for later upload
- **AI Summary**: Summarize chat history into a single file
- **Server Upload and Share**: Upload exported files to AnySpecs Hub or directly to Alibaba Cloud OSS
- **Terminal history and files diff history**: Export terminal history and files diff history(WIP)

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/anyspecs/anyspecs-cli.git
cd anyspecs-cli

# Install in development mode
pip install -e .

# Or install normally
pip install .
```

### Using pip

```bash
pip install anyspecs
```

## Quick Start

### List All Chat Sessions in this workspace

```bash
# List all chat sessions in this workspace from all sources
anyspecs list

# List only Cursor/Claude/Kiro sessions in this workspace
anyspecs list --source cursor/claude/kiro/augment/codex/all
```

### Export Chat Sessions

```bash
# Export current project's sessions to Markdown (default to .anyspecs/)
anyspecs export

# Export all sessions to HTML (default to .anyspecs/)
anyspecs export --all-projects --format html

# Export only today's sessions in local time
anyspecs export --now

# Export specific session
anyspecs export [--session-id abc123] [--format json]

# Export specific source sessions only(default is markdown) with custom output path
anyspecs export [--source claude/cursor/kiro/augment/codex] [--format markdown] [--output ./exports]

# Exported files are written to .anyspecs/ with full session IDs and a sidecar metadata file
# Example:
#   .anyspecs/codex-chat-anyspecs-cli-019d04f1-b713-7701-9c80-a9752539fa7f.md
#   .anyspecs/codex-chat-anyspecs-cli-019d04f1-b713-7701-9c80-a9752539fa7f.md.meta.json
```

### Setup config

```bash
# Setup specific AI provider
anyspecs setup [aihubmix/kimi/minimax/ppio/dify]
# list all the providers
anyspecs setup --list
# reset all the providers
anyspecs setup --reset
```

### Compress

```bash
# Check out anyspecs compress --help for more information
anyspecs compress [--input anyspecs.md] [--output anyspecs.specs] [--provider aihubmix/kimi/minimax/ppio/dify] ....
```
### Upload to share your specs

`upload` now supports two backends:

- `--hub-type anyspecs`: upload files to AnySpecs Hub / ASAP
- `--hub-type oss`: upload exported chat files directly to Alibaba Cloud OSS

#### Upload to AnySpecs Hub

> The default hub url is `https://hub.anyspecs.cn/`, and you can also deploy [ASAP](https://github.com/anyspecs/ASAP) on your own server.

Before your first hub upload, get your access token from `https://hub.anyspecs.cn/setting` and export it into your environment:

```bash
export ANYSPECS_TOKEN="44xxxxxxxxxxxxxx7a82"
# optional, defaults to https://hub.anyspecs.cn/
export ANYSPECS_UPLOAD_URL="https://hub.anyspecs.cn/"
```

```bash
# Default hub url is https://hub.anyspecs.cn/, you can also specify your server.
# Check remote specs repo
anyspecs upload --hub-type anyspecs --list
# Search specific repo
anyspecs upload --hub-type anyspecs --search "My specs"
# Upload a file to hub
anyspecs upload --hub-type anyspecs --file anyspecs.specs
# Upload a file to hub with description
anyspecs upload --hub-type anyspecs --file anyspecs.specs --description "My specs"
# Upload all files under a directory recursively
anyspecs upload --hub-type anyspecs --dir .anyspecs
# Upload and remove local files after success
anyspecs upload --hub-type anyspecs --dir .anyspecs --rm
# Use a custom server
anyspecs upload --hub-type anyspecs --url http://your-server:3000 --file anyspecs.specs
```

#### Upload directly to Alibaba Cloud OSS

OSS mode uploads exported files directly with the Alibaba Cloud `oss2` SDK. It does not use `--url` or `ANYSPECS_TOKEN`.

Required environment variables:

```bash
export ANYSPECS_UPLOAD_USERNAME="your-name"
export OSS_BUCKET="your-bucket"
export OSS_ENDPOINT="oss-cn-hangzhou.aliyuncs.com"
# or use OSS_REGION instead of OSS_ENDPOINT
# export OSS_REGION="cn-hangzhou"
export OSS_ACCESS_KEY_ID="your-ak"
export OSS_ACCESS_KEY_SECRET="your-sk"
```

```bash
# Upload one exported file
anyspecs upload --hub-type oss --file .anyspecs/chat.md

# Upload the default export directory recursively
anyspecs upload --hub-type oss --dir

# Upload and remove exported files plus sidecars after success
anyspecs upload --hub-type oss --dir --rm

# Upload a specific export directory recursively
anyspecs upload --hub-type oss --dir ./exports
```

OSS upload rules:

- Only exported files with a neighboring `.meta.json` sidecar are uploaded in `oss` mode
- Object key format is `<username>/<YYYY>/<MM>/<DD>/<filename>`
- Re-uploading the same exported file writes to the same OSS object key, so OSS overwrite behavior handles deduplication
- Sidecar metadata is also written to OSS object metadata for traceability
- `upload --rm` removes local files only after a successful upload; in `oss` mode it also removes the neighboring `.meta.json` sidecar

### More Functions

```shell
anyspecs --help
# positional arguments:
#   {list,export,compress,upload,setup}
#                         Available commands
#     list                List all chat sessions
#     export              Export chat sessions
#     compress            AI-compress chat sessions into .specs format (auto-loads config)
#     upload              Upload files to AnySpecs hub service
#     setup               Setup and manage AI provider configurations
# options:
#   -h, --help            show this help message and exit
#   --verbose, -v         Enable verbose logging
```

## Supported Sources

- Cursor AI: from Cursor's local SQLite databases
- Claude Code: from Claude Code's JSONL history files
- Augment Code: from VSCode's history databases
- Codex cli: from Codex cli's history files
- Kiro Records: from summary directory of Kiro

History mainly includes:
- Workspace-specific conversations
- Global chat storage
- Composer data and bubble conversations
- Project context and metadata

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/anyspecs/anyspecs-cli.git
cd anyspecs-cli

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black anyspecs/
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### v0.0.5
- Add Codex cli support
- Add Dify workflow process
- Add upload to remote server support
- Add direct Alibaba Cloud OSS upload support
- Add `upload --hub-type anyspecs|oss` and recursive directory upload
- Add stable export filenames with full session IDs and `.meta.json` sidecars

### v0.0.4
- Add Augment Code support
- Add version option

### v0.0.3
- Add AI Summary support(PPIO, Minimax, Kimi)

### v0.0.2
- Kiro Records support: Extract and export files from .kiro directory
- Default export directory: All exports now save to .anyspecs/ by default
- Workspace filtering: Cursor sessions now show only current workspace sessions in list command

### v0.0.1
- Initial release
- Support for Cursor AI and Claude Code
- Multiple export formats (Markdown, HTML, JSON)
- Upload functionality
- Project-based filtering
- Organized package structure

## Support

If you encounter any issues or have questions, please:

1. Check the [documentation](https://github.com/anyspecs/anyspecs-cli/wiki)
2. Search [existing issues](https://github.com/anyspecs/anyspecs-cli/issues)
3. Create a [new issue](https://github.com/anyspecs/anyspecs-cli/issues/new)
