"""
OpenCode chat history extractor.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

from ..core.extractors import BaseExtractor
from ..utils.paths import extract_project_name_from_path


class OpenCodeExtractor(BaseExtractor):
    """Extractor for OpenCode chat history."""

    def __init__(self):
        super().__init__("opencode")
        self.storage_root = Path.home() / ".local" / "share" / "opencode" / "storage"

    def extract_chats(self) -> List[Dict[str, Any]]:
        """Extract all chat data from OpenCode storage."""
        if self._should_use_sqlite():
            try:
                chats = self._extract_chats_from_sqlite()
                self.logger.info(f"Extracted {len(chats)} OpenCode chat sessions from SQLite")
                return chats
            except Exception as exc:
                self.logger.warning(
                    "Error reading OpenCode SQLite database %s: %s. Falling back to legacy storage.",
                    self._get_database_path(),
                    exc,
                )

        if not self.storage_root.exists():
            self.logger.debug(f"No OpenCode storage found at: {self.storage_root}")
            return []

        chats = self._extract_chats_from_files()
        self.logger.info(f"Extracted {len(chats)} OpenCode chat sessions")
        return chats

    def _extract_chats_from_files(self) -> List[Dict[str, Any]]:
        """Extract all chat data from the legacy JSON file storage."""
        chats: List[Dict[str, Any]] = []
        for session_file in self._list_session_files():
            session_data = self._read_json_file(session_file)
            if not session_data:
                continue

            chat = self._create_file_session_template(session_data, session_file)
            self._load_session_messages_from_files(chat)
            if chat["messages"]:
                chats.append(chat)

        return self._sort_chats(chats)

    def _extract_chats_from_sqlite(self) -> List[Dict[str, Any]]:
        """Extract all chat data from the SQLite storage used by OpenCode 1.2+."""
        chats: List[Dict[str, Any]] = []
        db_path = self._get_database_path()

        with closing(self._open_sqlite_connection(db_path)) as connection:
            for row in self._list_sqlite_sessions(connection):
                chat = self._create_sqlite_session_template(row, db_path)
                self._load_session_messages_from_sqlite(chat, connection)
                if chat["messages"]:
                    chats.append(chat)

        return self._sort_chats(chats)

    def _sort_chats(self, chats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort chats by last update time descending."""
        chats.sort(
            key=lambda chat: chat["metadata"].get("last_updated") or 0,
            reverse=True,
        )
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

    def _create_file_session_template(
        self,
        session_data: Dict[str, Any],
        session_file: Path,
    ) -> Dict[str, Any]:
        """Create a normalized session object from legacy file session metadata."""
        session_id = str(session_data.get("id") or session_file.stem)
        directory = str(session_data.get("directory") or "/")
        created_ms = self._parse_timestamp_ms(session_data.get("time", {}).get("created"))
        updated_ms = self._parse_timestamp_ms(session_data.get("time", {}).get("updated"))

        return self._build_chat(
            session_id=session_id,
            title=session_data.get("title"),
            directory=directory,
            created_ms=created_ms,
            updated_ms=updated_ms,
            version=session_data.get("version"),
            project_id=session_data.get("projectID"),
            slug=session_data.get("slug"),
            summary=session_data.get("summary", {}),
            source_reference=str(session_file),
        )

    def _create_sqlite_session_template(
        self,
        row: sqlite3.Row,
        db_path: Path,
    ) -> Dict[str, Any]:
        """Create a normalized session object from SQLite session metadata."""
        root_path = self._choose_project_root(
            session_directory=row["directory"],
            workspace_directory=row["workspace_directory"],
            project_worktree=row["project_worktree"],
        )
        project_name = str(row["project_name"] or "").strip()
        if not project_name:
            project_name = extract_project_name_from_path(root_path)

        summary = {
            "additions": row["summary_additions"],
            "deletions": row["summary_deletions"],
            "files": row["summary_files"],
            "diffs": self._parse_json_text(row["summary_diffs"]) or [],
        }

        return self._build_chat(
            session_id=row["id"],
            title=row["title"],
            directory=root_path,
            created_ms=row["time_created"],
            updated_ms=row["time_updated"],
            version=row["version"],
            project_id=row["project_id"],
            slug=row["slug"],
            summary=summary,
            source_reference=self._make_sqlite_source_reference(
                db_path,
                "session",
                row["id"],
            ),
            project_name=project_name,
            workspace_id=row["workspace_id"],
        )

    def _build_chat(
        self,
        session_id: str,
        title: Any,
        directory: str,
        created_ms: Optional[int],
        updated_ms: Optional[int],
        version: Any,
        project_id: Any,
        slug: Any,
        summary: Any,
        source_reference: str,
        project_name: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create the shared chat payload used by both storage backends."""
        normalized_project_name = project_name or extract_project_name_from_path(directory)
        chat = {
            "session_id": str(session_id),
            "messages": [],
            "project": {
                "name": normalized_project_name,
                "rootPath": directory,
            },
            "session": {
                "sessionId": str(session_id),
                "title": str(title or f"OpenCode session {str(session_id)[:8]}"),
                "createdAt": created_ms,
                "lastUpdatedAt": updated_ms,
            },
            "metadata": {
                "source_files": [source_reference],
                "created_at": self._to_unix_seconds(created_ms),
                "last_updated": self._to_unix_seconds(updated_ms),
                "opencode_version": version,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "slug": slug,
                "summary": summary or {},
            },
        }
        return chat

    def _load_session_messages_from_files(self, chat: Dict[str, Any]) -> None:
        """Load and flatten all messages for a legacy file-based session."""
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
            self._track_source_reference(chat, str(message_file))
            message_id = str(message_data.get("id") or "")
            part_records = self._load_file_part_records(message_id)
            self._append_message_parts(chat, message_data, part_records)

    def _load_session_messages_from_sqlite(
        self,
        chat: Dict[str, Any],
        connection: sqlite3.Connection,
    ) -> None:
        """Load and flatten all messages for a SQLite-backed session."""
        session_id = chat["session_id"]
        db_path = self._get_database_path()
        message_rows = connection.execute(
            """
            SELECT id, session_id, time_created, time_updated, data
            FROM message
            WHERE session_id = ?
            ORDER BY time_created ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        part_rows = connection.execute(
            """
            SELECT id, message_id, session_id, time_created, time_updated, data
            FROM part
            WHERE session_id = ?
            ORDER BY time_created ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        parts_by_message: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        for row in part_rows:
            part_data = self._parse_json_text(row["data"])
            if not isinstance(part_data, dict):
                self.logger.warning(
                    "Skipping OpenCode SQLite part %s because its data is not a JSON object",
                    row["id"],
                )
                continue

            part_data.setdefault("id", row["id"])
            if not isinstance(part_data.get("time"), dict):
                part_data["time"] = {}
            part_data["time"].setdefault("created", row["time_created"])
            message_key = str(row["message_id"])
            parts_by_message.setdefault(message_key, []).append(
                (
                    self._make_sqlite_source_reference(db_path, "part", row["id"]),
                    part_data,
                )
            )

        for row in message_rows:
            message_data = self._parse_json_text(row["data"])
            if not isinstance(message_data, dict):
                self.logger.warning(
                    "Skipping OpenCode SQLite message %s because its data is not a JSON object",
                    row["id"],
                )
                continue

            self._track_source_reference(
                chat,
                self._make_sqlite_source_reference(db_path, "message", row["id"]),
            )
            message_data.setdefault("id", row["id"])
            if not isinstance(message_data.get("time"), dict):
                message_data["time"] = {}
            message_data["time"].setdefault("created", row["time_created"])
            message_id = str(message_data.get("id") or row["id"])
            self._append_message_parts(
                chat,
                message_data,
                parts_by_message.get(message_id, []),
            )

    def _load_file_part_records(self, message_id: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Load all part records for a legacy file-backed message."""
        if not message_id:
            return []

        part_dir = self.storage_root / "part" / message_id
        if not part_dir.exists():
            return []

        part_records: List[Tuple[str, Dict[str, Any]]] = []
        for part_file in sorted(part_dir.glob("prt_*.json"), key=lambda path: path.name):
            part_data = self._read_json_file(part_file)
            if not part_data:
                continue
            part_records.append((str(part_file), part_data))

        return part_records

    def _append_message_parts(
        self,
        chat: Dict[str, Any],
        message_data: Dict[str, Any],
        part_records: Sequence[Tuple[str, Dict[str, Any]]],
    ) -> None:
        """Convert OpenCode message parts into exported messages."""
        message_id = str(message_data.get("id") or "")
        if not message_id:
            return

        role = str(message_data.get("role") or "assistant")
        timestamp_ms = self._parse_timestamp_ms(message_data.get("time", {}).get("created"))
        timestamp = self._to_unix_seconds(timestamp_ms)

        for source_reference, part_data in part_records:
            self._track_source_reference(chat, source_reference)
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
                        source=source_reference,
                    )
                continue

            if part_type == "tool":
                self._append_tool_messages(chat, part_data, timestamp, source_reference)
                continue

            if part_type == "file":
                self._append_file_message(chat, part_data, timestamp, source_reference)
                continue

            if part_type == "patch":
                self._append_patch_message(chat, part_data, timestamp, source_reference)

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

    def _track_source_reference(self, chat: Dict[str, Any], source_reference: str) -> None:
        """Track source references in metadata."""
        if source_reference not in chat["metadata"]["source_files"]:
            chat["metadata"]["source_files"].append(source_reference)

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

    def _parse_json_text(self, value: Any) -> Optional[Any]:
        """Parse JSON text into Python data."""
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            self.logger.warning("Error parsing OpenCode JSON payload: %s", exc)
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

    def _should_use_sqlite(self) -> bool:
        """Return True when the OpenCode SQLite storage is available and supported."""
        db_path = self._get_database_path()
        if not db_path.exists():
            return False

        try:
            with closing(self._open_sqlite_connection(db_path)) as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                        """
                    ).fetchall()
                }
        except sqlite3.DatabaseError as exc:
            self.logger.warning("Unable to inspect OpenCode SQLite database %s: %s", db_path, exc)
            return False

        required_tables = {"session", "message", "part"}
        if not required_tables.issubset(tables):
            self.logger.warning(
                "OpenCode SQLite database %s is missing required tables: %s",
                db_path,
                ", ".join(sorted(required_tables - tables)),
            )
            return False
        return True

    def _get_database_path(self) -> Path:
        """Get the SQLite database path for the current storage root."""
        return self.storage_root.parent / "opencode.db"

    def _open_sqlite_connection(self, db_path: Path) -> sqlite3.Connection:
        """Open the OpenCode SQLite database in read-only mode."""
        db_uri = f"{db_path.resolve().as_uri()}?{urlencode({'mode': 'ro'})}"
        connection = sqlite3.connect(db_uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _list_sqlite_sessions(self, connection: sqlite3.Connection) -> Iterable[sqlite3.Row]:
        """List session rows from the OpenCode SQLite database."""
        return connection.execute(
            """
            SELECT
                s.id,
                s.project_id,
                s.workspace_id,
                s.slug,
                s.directory,
                s.title,
                s.version,
                s.summary_additions,
                s.summary_deletions,
                s.summary_files,
                s.summary_diffs,
                s.time_created,
                s.time_updated,
                p.name AS project_name,
                p.worktree AS project_worktree,
                w.directory AS workspace_directory
            FROM session AS s
            LEFT JOIN project AS p ON p.id = s.project_id
            LEFT JOIN workspace AS w ON w.id = s.workspace_id
            ORDER BY s.time_updated DESC, s.id DESC
            """
        ).fetchall()

    def _choose_project_root(
        self,
        session_directory: Any,
        workspace_directory: Any,
        project_worktree: Any,
    ) -> str:
        """Choose the best available root path for project filtering/export metadata."""
        for value in (session_directory, workspace_directory, project_worktree):
            text = str(value or "").strip()
            if text:
                return text
        return "/"

    def _make_sqlite_source_reference(
        self,
        db_path: Path,
        record_type: str,
        record_id: str,
    ) -> str:
        """Create a stable logical source reference for SQLite-backed records."""
        return f"{db_path}#{record_type}:{record_id}"
