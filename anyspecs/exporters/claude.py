"""
Claude Code chat history extractor.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.extractors import BaseExtractor
from ..utils.paths import extract_project_name_from_path, get_claude_projects_root


class ClaudeExtractor(BaseExtractor):
    """Extractor for Claude Code chat history."""

    SUPPORTED_CLI_VERSIONS = (
        "1.0.98",
        "2.1.59",
        "2.1.62",
        "2.1.63",
        "2.1.71",
        "2.1.72",
    )

    def __init__(self):
        super().__init__("claude")
        self.projects_root = get_claude_projects_root()

    def extract_chats(self) -> List[Dict[str, Any]]:
        """Extract all chat data from Claude Code."""
        history_files = self._list_history_files()
        if not history_files:
            self.logger.debug("No Claude Code history files found.")
            return []

        sessions: Dict[str, Dict[str, Any]] = {}

        for file_info in history_files:
            entries = self._read_history_file(file_info["path"])
            for entry in entries:
                session_id = entry.get("sessionId")
                if not session_id:
                    continue

                session = sessions.setdefault(
                    session_id,
                    self._create_session_template(session_id),
                )

                self._track_source_file(session, file_info["path"])
                self._apply_entry_metadata(session, entry)
                self._process_entry(session, entry)

        chats = [session for session in sessions.values() if session["messages"]]
        chats.sort(
            key=lambda chat: chat["session"].get("createdAt") or 0,
            reverse=True,
        )

        self.logger.debug(f"Extracted {len(chats)} Claude chat sessions")
        return chats

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List available chat sessions with metadata."""
        chats = self.extract_chats()
        sessions = []

        for chat in chats:
            session_id = chat.get("session", {}).get("sessionId", "unknown")[:8]
            project_name = chat.get("project", {}).get("name", "Unknown Project")
            msg_count = len(chat.get("messages", []))

            date_str = "Unknown date"
            created_at = chat.get("session", {}).get("createdAt")
            if created_at:
                try:
                    if created_at > 1e10:
                        created_at = created_at / 1000
                    date_obj = datetime.fromtimestamp(created_at)
                    date_str = date_obj.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

            preview = "No messages"
            messages = chat.get("messages", [])
            if messages:
                first_msg = str(messages[0].get("content", ""))
                preview = (
                    first_msg[:60] + "..." if len(first_msg) > 60 else first_msg
                ).replace("\n", " ")

            sessions.append(
                {
                    "session_id": session_id,
                    "project": project_name,
                    "date": date_str,
                    "message_count": msg_count,
                    "preview": preview,
                    "source_files": len(chat.get("metadata", {}).get("source_files", [])),
                }
            )

        return sessions

    def get_version_support_info(self) -> Dict[str, Any]:
        """Inspect local Claude history files and summarize version support."""
        history_files = self._list_history_files()
        detected_versions = set()

        for file_info in history_files:
            version = self._read_version_from_history_file(file_info["path"])
            if version:
                detected_versions.add(version)

        supported_versions = sorted(
            self.SUPPORTED_CLI_VERSIONS,
            key=self._version_sort_key,
        )
        detected_versions_sorted = sorted(
            detected_versions,
            key=self._version_sort_key,
        )
        unsupported_versions = sorted(
            [version for version in detected_versions_sorted if version not in supported_versions],
            key=self._version_sort_key,
        )

        return {
            "supported_versions": supported_versions,
            "detected_versions": detected_versions_sorted,
            "unsupported_versions": unsupported_versions,
            "has_sessions": bool(history_files),
        }

    def _list_history_files(self) -> List[Dict[str, Any]]:
        """List all Claude history files across all project directories."""
        if not self.projects_root.exists():
            self.logger.debug(
                f"No Claude Code history found at: {self.projects_root}"
            )
            return []

        history_files = []
        for file_path in self.projects_root.glob("*/*.jsonl"):
            try:
                stat = file_path.stat()
                history_files.append(
                    {
                        "path": file_path,
                        "name": file_path.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime),
                    }
                )
            except Exception as exc:
                self.logger.warning(f"Error reading file info for {file_path}: {exc}")

        return sorted(history_files, key=lambda item: item["modified"], reverse=True)

    def _read_history_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Read and parse a JSONL history file."""
        entries = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        self.logger.warning(
                            f"Invalid JSON on line {line_num} in {file_path}: {exc}"
                        )
        except Exception as exc:
            self.logger.error(f"Error reading file {file_path}: {exc}")

        return entries

    def _read_version_from_history_file(self, file_path: Path) -> Optional[str]:
        """Read the first available Claude version from a history file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as exc:
                        self.logger.warning(
                            f"Invalid JSON on line {line_num} in {file_path}: {exc}"
                        )
                        return None

                    version = entry.get("version")
                    if version:
                        return version
        except Exception as exc:
            self.logger.error(f"Error reading file {file_path}: {exc}")

        return None

    def _create_session_template(self, session_id: str) -> Dict[str, Any]:
        """Create a session template."""
        return {
            "session_id": session_id,
            "messages": [],
            "project": {
                "name": "Unknown Project",
                "rootPath": "/",
            },
            "session": {
                "sessionId": session_id,
                "title": f"Claude Session {session_id[:8]}",
                "createdAt": None,
                "lastUpdatedAt": None,
            },
            "metadata": {
                "source_files": [],
                "created_at": None,
                "last_updated": None,
                "claude_version": None,
            },
        }

    def _track_source_file(self, session: Dict[str, Any], file_path: Path) -> None:
        """Track source file in metadata."""
        source_file = str(file_path)
        if source_file not in session["metadata"]["source_files"]:
            session["metadata"]["source_files"].append(source_file)

    def _apply_entry_metadata(
        self, session: Dict[str, Any], entry: Dict[str, Any]
    ) -> None:
        """Apply shared metadata from a Claude entry."""
        cwd = entry.get("cwd")
        if cwd:
            session["project"]["rootPath"] = cwd
            session["project"]["name"] = extract_project_name_from_path(cwd)

        version = entry.get("version")
        if version:
            session["metadata"]["claude_version"] = version

        timestamp = entry.get("timestamp")
        self._update_session_timestamps(session, timestamp)

    def _process_entry(self, session: Dict[str, Any], entry: Dict[str, Any]) -> None:
        """Process a single Claude history entry."""
        entry_type = entry.get("type")
        if entry_type in {
            "system",
            "progress",
            "queue-operation",
            "file-history-snapshot",
            "last-prompt",
        }:
            return

        message = entry.get("message")
        if not isinstance(message, dict):
            return

        timestamp = entry.get("timestamp")
        role = message.get("role")
        content = message.get("content")

        if isinstance(content, str):
            if role == "user" and content:
                session["messages"].append(
                    {
                        "role": "user",
                        "content": content,
                        "timestamp": timestamp,
                    }
                )
            return

        if not isinstance(content, list):
            return

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "thinking":
                continue

            if block_type == "text":
                text = block.get("text")
                if text:
                    session["messages"].append(
                        {
                            "role": "assistant" if role == "assistant" else "user",
                            "content": text,
                            "timestamp": timestamp,
                        }
                    )
                continue

            if block_type == "tool_use":
                tool_name = block.get("name", "Unknown")
                tool_input = block.get("input")
                content_text = f"**Tool Call: {tool_name}**\n\n"
                if tool_input is not None:
                    content_text += (
                        "```json\n"
                        f"{json.dumps(tool_input, indent=2, ensure_ascii=False, default=str)}\n"
                        "```"
                    )
                session["messages"].append(
                    {
                        "role": "assistant",
                        "content": content_text,
                        "timestamp": timestamp,
                    }
                )
                continue

            if block_type == "tool_result":
                result_content = block.get("content", "")
                tool_use_id = block.get("tool_use_id", "unknown")
                session["messages"].append(
                    {
                        "role": "system",
                        "content": self._format_tool_result(
                            tool_use_id=tool_use_id,
                            result_content=result_content,
                        ),
                        "timestamp": timestamp,
                    }
                )

    def _format_tool_result(self, tool_use_id: str, result_content: Any) -> str:
        """Format a Claude tool result message."""
        content = f"**Tool Result: {tool_use_id}**\n\n"
        if isinstance(result_content, str):
            content += f"```\n{result_content}\n```"
            return content

        content += (
            "```json\n"
            f"{json.dumps(result_content, indent=2, ensure_ascii=False, default=str)}\n"
            "```"
        )
        return content

    def _update_session_timestamps(
        self, session: Dict[str, Any], timestamp_value: Optional[Any]
    ) -> None:
        """Update session timestamps from an entry timestamp."""
        timestamp = self._parse_timestamp(timestamp_value)
        if timestamp is None:
            return

        if session["metadata"]["created_at"] is None:
            session["metadata"]["created_at"] = timestamp
            session["session"]["createdAt"] = timestamp * 1000

        session["metadata"]["last_updated"] = timestamp
        session["session"]["lastUpdatedAt"] = timestamp * 1000

    def _parse_timestamp(self, timestamp_value: Optional[Any]) -> Optional[int]:
        """Parse ISO or numeric timestamps to Unix seconds."""
        if timestamp_value is None:
            return None

        if isinstance(timestamp_value, (int, float)):
            timestamp = float(timestamp_value)
            if timestamp > 1e10:
                timestamp /= 1000
            return int(timestamp)

        if isinstance(timestamp_value, str):
            try:
                return int(float(timestamp_value))
            except ValueError:
                pass

            try:
                dt = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
                return int(dt.timestamp())
            except ValueError:
                return None

        return None

    def _version_sort_key(self, version: str) -> List[Any]:
        """Sort versions naturally while keeping exact string comparison for support."""
        parts: List[Any] = []
        chunk = ""
        current_is_digit: Optional[bool] = None

        for char in version:
            is_digit = char.isdigit()
            if current_is_digit is None or is_digit == current_is_digit:
                chunk += char
            else:
                parts.append(int(chunk) if current_is_digit else chunk)
                chunk = char
            current_is_digit = is_digit

        if chunk:
            parts.append(int(chunk) if current_is_digit else chunk)

        return parts
