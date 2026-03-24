"""
OpenCode chat history extractor.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.extractors import BaseExtractor
from ..utils.paths import extract_project_name_from_path


class OpenCodeExtractor(BaseExtractor):
    """Extractor for OpenCode chat history."""

    def __init__(self):
        super().__init__("opencode")
        self.storage_root = Path.home() / ".local" / "share" / "opencode" / "storage"

    def extract_chats(self) -> List[Dict[str, Any]]:
        """Extract all chat data from OpenCode storage."""
        if not self.storage_root.exists():
            self.logger.debug(f"No OpenCode storage found at: {self.storage_root}")
            return []

        chats: List[Dict[str, Any]] = []
        for session_file in self._list_session_files():
            session_data = self._read_json_file(session_file)
            if not session_data:
                continue

            chat = self._create_session_template(session_data, session_file)
            self._load_session_messages(chat)
            if chat["messages"]:
                chats.append(chat)

        chats.sort(
            key=lambda chat: chat["metadata"].get("last_updated") or 0,
            reverse=True,
        )
        self.logger.info(f"Extracted {len(chats)} OpenCode chat sessions")
        return chats

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List available OpenCode chat sessions."""
        sessions = []
        for chat in self.extract_chats():
            created_at = chat["metadata"].get("created_at")
            date_str = "Unknown date"
            if created_at:
                try:
                    date_str = datetime.fromtimestamp(created_at).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                except Exception:
                    pass

            sessions.append(
                {
                    "session_id": chat["session_id"],
                    "project": chat["project"]["name"],
                    "date": date_str,
                    "message_count": len(chat["messages"]),
                    "preview": self._generate_preview(chat),
                    "source_files": len(chat["metadata"].get("source_files", [])),
                }
            )

        return sessions

    def _list_session_files(self) -> List[Path]:
        """List all OpenCode session files."""
        return sorted(
            self.storage_root.glob("session/*/ses_*.json"),
            key=lambda path: path.name,
        )

    def _create_session_template(
        self,
        session_data: Dict[str, Any],
        session_file: Path,
    ) -> Dict[str, Any]:
        """Create a normalized session object from OpenCode session metadata."""
        session_id = str(session_data.get("id") or session_file.stem)
        directory = str(session_data.get("directory") or "/")
        created_ms = self._parse_timestamp_ms(session_data.get("time", {}).get("created"))
        updated_ms = self._parse_timestamp_ms(session_data.get("time", {}).get("updated"))

        chat = {
            "session_id": session_id,
            "messages": [],
            "project": {
                "name": extract_project_name_from_path(directory),
                "rootPath": directory,
            },
            "session": {
                "sessionId": session_id,
                "title": session_data.get("title") or f"OpenCode session {session_id[:8]}",
                "createdAt": created_ms,
                "lastUpdatedAt": updated_ms,
            },
            "metadata": {
                "source_files": [str(session_file)],
                "created_at": self._to_unix_seconds(created_ms),
                "last_updated": self._to_unix_seconds(updated_ms),
                "opencode_version": session_data.get("version"),
                "project_id": session_data.get("projectID"),
                "slug": session_data.get("slug"),
                "summary": session_data.get("summary", {}),
            },
        }
        return chat

    def _load_session_messages(self, chat: Dict[str, Any]) -> None:
        """Load and flatten all messages for a session."""
        session_id = chat["session_id"]
        message_dir = self.storage_root / "message" / session_id
        if not message_dir.exists():
            return

        message_records = []
        for message_file in message_dir.glob("msg_*.json"):
            message_data = self._read_json_file(message_file)
            if not message_data:
                continue
            created_at = self._parse_timestamp_ms(message_data.get("time", {}).get("created"))
            message_records.append((created_at or 0, message_file.name, message_file, message_data))

        for _, _, message_file, message_data in sorted(message_records):
            self._track_source_file(chat, message_file)
            self._append_message_parts(chat, message_data)

    def _append_message_parts(
        self,
        chat: Dict[str, Any],
        message_data: Dict[str, Any],
    ) -> None:
        """Convert OpenCode message parts into exported messages."""
        message_id = str(message_data.get("id") or "")
        if not message_id:
            return

        part_dir = self.storage_root / "part" / message_id
        if not part_dir.exists():
            return

        role = str(message_data.get("role") or "assistant")
        timestamp_ms = self._parse_timestamp_ms(message_data.get("time", {}).get("created"))
        timestamp = self._to_unix_seconds(timestamp_ms)

        for part_file in sorted(part_dir.glob("prt_*.json"), key=lambda path: path.name):
            part_data = self._read_json_file(part_file)
            if not part_data:
                continue

            self._track_source_file(chat, part_file)
            part_type = part_data.get("type")

            if part_type in {"reasoning", "step-start", "step-finish", "compaction"}:
                continue

            if part_type == "text":
                content = str(part_data.get("text") or "").strip()
                if content:
                    self._append_export_message(
                        chat=chat,
                        role=role,
                        content=content,
                        timestamp=timestamp,
                        source=str(part_file),
                    )
                continue

            if part_type == "tool":
                self._append_tool_messages(chat, part_data, timestamp, str(part_file))
                continue

            if part_type == "file":
                self._append_file_message(chat, part_data, timestamp, str(part_file))
                continue

            if part_type == "patch":
                self._append_patch_message(chat, part_data, timestamp, str(part_file))

    def _append_tool_messages(
        self,
        chat: Dict[str, Any],
        part_data: Dict[str, Any],
        timestamp: Optional[int],
        source: str,
    ) -> None:
        """Append tool call and result messages for a tool part."""
        tool_name = part_data.get("tool", "unknown")
        call_id = part_data.get("callID", "unknown")
        state = part_data.get("state") if isinstance(part_data.get("state"), dict) else {}

        if state.get("input") is not None:
            self._append_export_message(
                chat=chat,
                role="assistant",
                content=(
                    f"**Tool Call: {tool_name}**\n\n"
                    f"{self._format_block(state.get('input'), default_language='json')}"
                ),
                timestamp=timestamp,
                source=source,
            )

        output_value = state.get("output")
        if output_value is not None:
            self._append_export_message(
                chat=chat,
                role="system",
                content=(
                    f"**Tool Output: {call_id}**\n\n"
                    f"{self._format_block(output_value)}"
                ),
                timestamp=timestamp,
                source=source,
            )

    def _append_file_message(
        self,
        chat: Dict[str, Any],
        part_data: Dict[str, Any],
        timestamp: Optional[int],
        source: str,
    ) -> None:
        """Append a file reference message."""
        payload = {
            "filename": part_data.get("filename"),
            "mime": part_data.get("mime"),
            "url": part_data.get("url"),
            "source": part_data.get("source"),
        }
        self._append_export_message(
            chat=chat,
            role="user",
            content=(
                f"**File Reference: {part_data.get('filename', 'unknown')}**\n\n"
                f"{self._format_block(payload, default_language='json')}"
            ),
            timestamp=timestamp,
            source=source,
        )

    def _append_patch_message(
        self,
        chat: Dict[str, Any],
        part_data: Dict[str, Any],
        timestamp: Optional[int],
        source: str,
    ) -> None:
        """Append a patch summary message."""
        payload = {
            "hash": part_data.get("hash"),
            "files": part_data.get("files", []),
        }
        self._append_export_message(
            chat=chat,
            role="system",
            content=(
                f"**Patch: {part_data.get('hash', 'unknown')}**\n\n"
                f"{self._format_block(payload, default_language='json')}"
            ),
            timestamp=timestamp,
            source=source,
        )

    def _append_export_message(
        self,
        chat: Dict[str, Any],
        role: str,
        content: str,
        timestamp: Optional[int],
        source: str,
    ) -> None:
        """Append a normalized exported message."""
        chat["messages"].append(
            {
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "source": source,
            }
        )
        self._update_session_timestamp(chat, timestamp)

    def _track_source_file(self, chat: Dict[str, Any], file_path: Path) -> None:
        """Track source files in metadata."""
        source_file = str(file_path)
        if source_file not in chat["metadata"]["source_files"]:
            chat["metadata"]["source_files"].append(source_file)

    def _generate_preview(self, chat: Dict[str, Any]) -> str:
        """Generate a session preview."""
        title = str(chat.get("session", {}).get("title") or "").strip()
        if title:
            return title

        for message in chat.get("messages", []):
            if message.get("role") == "user":
                content = str(message.get("content") or "").replace("\n", " ").strip()
                if len(content) > 100:
                    content = content[:100] + "..."
                if content:
                    return content

        return "No messages"

    def _update_session_timestamp(
        self,
        chat: Dict[str, Any],
        timestamp: Optional[int],
    ) -> None:
        """Keep session timestamps in sync with appended messages."""
        if timestamp is None:
            return

        if chat["metadata"]["created_at"] is None:
            chat["metadata"]["created_at"] = timestamp
            chat["session"]["createdAt"] = timestamp * 1000

        chat["metadata"]["last_updated"] = timestamp
        chat["session"]["lastUpdatedAt"] = timestamp * 1000

    def _read_json_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read a JSON file safely."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            self.logger.warning(f"Error reading OpenCode file {path}: {exc}")
            return None

    def _parse_timestamp_ms(self, value: Any) -> Optional[int]:
        """Parse OpenCode millisecond timestamps."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value))
            except ValueError:
                return None
        return None

    def _to_unix_seconds(self, value_ms: Optional[int]) -> Optional[int]:
        """Convert millisecond timestamps to Unix seconds."""
        if value_ms is None:
            return None
        timestamp = float(value_ms)
        if timestamp > 1e10:
            timestamp /= 1000
        return int(timestamp)

    def _format_block(self, value: Any, default_language: str = "") -> str:
        """Format arbitrary values in fenced code blocks."""
        text = self._stringify_value(value)
        language = default_language
        if not language and self._looks_like_json(text):
            language = "json"

        if language:
            return f"```{language}\n{text}\n```"
        return f"```\n{text}\n```"

    def _stringify_value(self, value: Any) -> str:
        """Convert arbitrary values into readable text."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    def _looks_like_json(self, value: str) -> bool:
        """Check if a string looks like JSON."""
        text = value.strip()
        if not text:
            return False
        if not (
            (text.startswith("{") and text.endswith("}"))
            or (text.startswith("[") and text.endswith("]"))
        ):
            return False
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False
