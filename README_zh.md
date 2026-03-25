<div align="center">

  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/headerDark.svg" />
    <img src="assets/headerLight.svg" alt="AnySpecs CLI" />
  </picture>

***Code is cheap, Show me Any Specs.***
  
[:page_facing_up: English Version](https://github.com/anyspecs/anyspecs-cli/blob/main/README.md) |
[:gear: 快速上手](#quick-start) |
[:thinking: 报告问题](https://github.com/anyspecs/anyspecs-cli/issues/new/choose)

</div>

AnySpecs CLI 是一个统一的命令行工具，用于从多个 AI 助手导出聊天记录。它目前支持 **Cursor AI**、**Claude Code**、**Augment Code**、**Codex CLI**、**OpenCode**、**Windsurf** 和 **Kiro Records**，并支持多种导出格式，包括 Markdown、HTML 和 JSON。

## ✨ 功能特性

- **多源支持**: 从 Cursor、Claude、Augment、Codex、OpenCode、Windsurf、Kiro 等来源导出（持续增加）。
- **多种导出格式**: 支持 Markdown、HTML 和 JSON。
- **项目与工作区过滤**: 按项目或当前目录导出聊天会话。
- **灵活的会话管理**: 列表、筛选和导出特定的聊天会话。
- **默认导出目录**: 所有导出的文件默认保存到 `.anyspecs/` 目录，统一管理。
- **稳定导出文件**: 导出文件名使用完整 `session_id`，并生成配套 `.meta.json` sidecar 供后续上传。
- **AI 总结**: 将聊天记录总结为结构化 `.specs` 文件。
- **上传分享**: 将导出的文件上传到 AnySpecs Hub / ASAP，或直接上传到阿里云 OSS。
- **终端历史与文件变更**: 导出终端历史与文件 diff（开发中）。

## 📦 安装

### 从源代码安装

```bash
# 克隆仓库
git clone https://github.com/anyspecs/anyspecs-cli.git
cd anyspecs-cli

# 以开发模式安装
pip install -e .

# 或者普通安装
pip install .
```

### 使用 pip 安装

```bash
pip install anyspecs
```

## 🚀 快速上手

### 列出当前工作区的所有聊天会话

```bash
# 列出所有来源的当前工作区的聊天会话
anyspecs list

# 仅列出当前工作区的 Cursor/Claude/Kiro/Augment/Codex/OpenCode/Windsurf 会话
anyspecs list --source cursor/claude/kiro/augment/codex/opencode/windsurf/all

# 显示详细信息
anyspecs list --verbose
```

### 导出聊天会话

```bash
# 导出当前项目的会话为 Markdown (默认到 .anyspecs/ 目录)
anyspecs export

# 导出所有项目的会话为 HTML (默认到 .anyspecs/ 目录)
anyspecs export --all-projects --format html

# 仅导出本地时区“今天”的会话
anyspecs export --now

# 导出指定的会话
anyspecs export --session-id abc123 --format json

# 导出指定来源（默认 markdown）并自定义输出目录
anyspecs export --source claude/cursor/kiro/augment/codex/opencode/windsurf --format markdown --output ./exports

# 导出文件默认写入 .anyspecs/，文件名包含完整 session_id，并附带 sidecar 元数据
# 例如：
#   .anyspecs/codex-chat-anyspecs-cli-019d04f1-b713-7701-9c80-a9752539fa7f.md
#   .anyspecs/codex-chat-anyspecs-cli-019d04f1-b713-7701-9c80-a9752539fa7f.md.meta.json
```

### 配置（Setup）

```bash
# 配置指定的 AI 提供方
anyspecs setup [aihubmix/kimi/minimax/ppio/dify]
# 列出所有已配置的提供方
anyspecs setup --list
# 重置所有配置
anyspecs setup --reset
```

### 压缩（Compress）

```bash
# 更多参数参考 anyspecs compress --help
anyspecs compress [--input anyspecs.md] [--output anyspecs.specs] \
  [--provider aihubmix/kimi/minimax/ppio/dify] ...
```

### 上传分享你的 specs（Upload）

`upload` 现在支持两种后端：

- `--hub-type anyspecs`: 上传到 AnySpecs Hub / ASAP
- `--hub-type oss`: 直接上传到阿里云 OSS

#### 上传到 AnySpecs Hub

> 默认上传地址为官方 Hub `https://hub.anyspecs.cn/`，你也可以自建 [ASAP](https://github.com/anyspecs/ASAP)。

首次上传前，请在 `https://hub.anyspecs.cn/setting` 生成访问令牌，并导出到环境变量，例如：

```bash
export ANYSPECS_TOKEN="44xxxxxxxxxxxxxx7a82"
# 可选，默认就是 https://hub.anyspecs.cn/
export ANYSPECS_UPLOAD_URL="https://hub.anyspecs.cn/"
```

```bash
# 检查远端仓库
anyspecs upload --hub-type anyspecs --list
# 搜索特定仓库
anyspecs upload --hub-type anyspecs --search "My specs"
# 上传文件到 Hub
anyspecs upload --hub-type anyspecs --file anyspecs.specs
# 携带描述信息上传
anyspecs upload --hub-type anyspecs --file anyspecs.specs --description "My specs"
# 递归上传目录下所有文件
anyspecs upload --hub-type anyspecs --dir .anyspecs
# 上传成功后删除本地文件
anyspecs upload --hub-type anyspecs --dir .anyspecs --rm
# 使用自定义服务器
anyspecs upload --hub-type anyspecs --url http://your-server:3000 --file anyspecs.specs
```

#### 直接上传到阿里云 OSS

OSS 模式通过阿里云 `oss2` SDK 直传，不使用 `--url`，也不依赖 `ANYSPECS_TOKEN`。

必需环境变量：

```bash
export ANYSPECS_UPLOAD_USERNAME="your-name"
export OSS_BUCKET="your-bucket"
export OSS_ENDPOINT="oss-cn-hangzhou.aliyuncs.com"
# 或者不用 OSS_ENDPOINT，改用 OSS_REGION
# export OSS_REGION="cn-hangzhou"
export OSS_ACCESS_KEY_ID="your-ak"
export OSS_ACCESS_KEY_SECRET="your-sk"
```

```bash
# 上传单个导出文件
anyspecs upload --hub-type oss --file .anyspecs/chat.md

# 使用斜杠日期目录上传
anyspecs upload --hub-type oss --file .anyspecs/chat.md --date-format yyyy/mm/dd

# 递归上传默认导出目录
anyspecs upload --hub-type oss --dir

# 递归上传指定导出目录
anyspecs upload --hub-type oss --dir ./exports

# 上传成功后删除导出文件及其 sidecar
anyspecs upload --hub-type oss --dir --rm
```

OSS 上传规则：

- `oss` 模式只会上传旁边有 `.meta.json` sidecar 的导出文件
- `--date-format` 支持 `yyyy-mm-dd` 和 `yyyy/mm/dd`，默认 `yyyy-mm-dd`
- OSS object key 格式为 `<username>/<date>/<filename>`，例如 `<username>/2026-03-19/chat.md`
- 同一个导出文件重复上传会落到同一个 object key，由 OSS 覆盖写实现去重
- sidecar 中的来源、session、格式、日期等信息会同步写入 OSS object metadata，且上传时 `x-oss-meta-chat-date` 会使用所选日期格式
- `upload --rm` 只会在上传成功后删除本地文件；`oss` 模式还会一并删除相邻的 `.meta.json` sidecar

## 🔌 支持的来源

### Cursor AI

从 Cursor 的本地 SQLite 数据库中提取聊天记录，包括：
- 特定于工作区的对话
- 全局聊天存储
- 编辑器中的对话和气泡对话
- 项目上下文和元数据

### Claude Code

从 Claude Code 的 JSONL 历史文件中提取聊天记录，包括：
- 用户消息和 AI 回复
- 工具调用和结果
- 会话元数据
- 项目上下文

### Kiro Records

从 `.kiro` 目录中提取和合并 Markdown 文档，包括：
- 文件元数据 (名称、修改时间)
- 自动项目摘要检测

### OpenCode

从 OpenCode 的本地 SQLite 数据库（`opencode.db`）中提取聊天记录，旧版本会回退到原始存储目录，包括：
- SQLite 中的 session / message / part 表
- 旧版 session / message / part 三层结构
- 用户消息、AI 回复
- 工具调用和工具输出
- 文件引用与 patch 元数据

### Windsurf

从 Windsurf 的本地工作区元数据与可读会话存储中提取聊天记录，包括：
- 工作区路径与项目上下文
- 用户消息、AI 回复
- 会话标题与时间戳
- 导出所需的来源元数据

## 🤝 贡献

欢迎任何形式的贡献！请随时提交拉取请求 (Pull Request)。

### 开发设置

```bash
# 克隆仓库
git clone https://github.com/anyspecs/anyspecs-cli.git
cd anyspecs-cli

# 以开发模式安装并包含开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 格式化代码
black anyspecs/

# 类型检查
mypy anyspecs/
```

## 📄 许可证

本项目采用 MIT 许可证 - 详情请见 [LICENSE](LICENSE) 文件。

## 📜 更新日志

### v0.0.5
- 新增 Codex CLI 支持
- 新增 Dify 工作流压缩支持
- 新增上传到远程服务器（Hub/ASAP）
- 新增直传阿里云 OSS 支持
- 新增 `upload --hub-type anyspecs|oss` 与目录递归上传
- 导出文件名改为完整 `session_id`，并生成 `.meta.json` sidecar

### v0.0.4
- 新增 Augment Code 支持
- 新增 `--version` 选项

### v0.0.3
- 新增 AI 总结支持（PPIO、MiniMax、Kimi）

### v0.0.2
- Kiro Records 支持；默认导出目录 `.anyspecs/`；工作区过滤优化

### v0.0.1
- 初始版本：支持 Cursor/Claude；支持 Markdown/HTML/JSON 导出

## 💬 支持

如果您遇到任何问题或有任何疑问，请：

1.  查看 [文档](https://github.com/anyspecs/anyspecs-cli/wiki) (如果存在)。
2.  搜索 [现有的问题](https://github.com/anyspecs/anyspecs-cli/issues)。
3.  创建一个 [新的问题](https://github.com/anyspecs/anyspecs-cli/issues/new)。 
