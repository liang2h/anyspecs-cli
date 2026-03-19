"""
Codex chat history extractor.
"""

import json
import pathlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.extractors import BaseExtractor
from ..utils.paths import extract_project_name_from_path


class CodexExtractor(BaseExtractor):
    """Extractor for Codex chat history."""

    def __init__(self):
        super().__init__("codex")
        self.history_dir = pathlib.Path.home() / ".codex"

    def extract_chats(self) -> List[Dict[str, Any]]:
        """Extract all chat data from Codex."""
        if not self.history_dir.exists():
            self.logger.debug(f"No Codex history found at: {self.history_dir}")
            return []

        current_project_path = str(pathlib.Path.cwd())
        self.logger.debug(f"Current project path: {current_project_path}")

        session_titles = self._load_session_titles()
        all_sessions: Dict[str, Dict[str, Any]] = {}

        session_sessions = self._extract_from_session_files(session_titles)
        all_sessions.update(session_sessions)

        history_sessions = self._extract_from_history_jsonl(
            existing_session_ids=set(session_sessions),
            session_titles=session_titles,
        )
        all_sessions.update(history_sessions)

        log_sessions = self._extract_from_log_files(current_project_path)
        all_sessions.update(log_sessions)

        config_sessions = self._extract_from_config(current_project_path)
        all_sessions.update(config_sessions)

        chats = [session for session in all_sessions.values() if session["messages"]]
        chats.sort(
            key=lambda chat: chat["metadata"].get("last_updated") or 0,
            reverse=True,
        )

        self.logger.info(f"Extracted {len(chats)} Codex chat sessions")
        return chats

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List available Codex chat sessions with metadata."""
        chats = self.extract_chats()
        sessions = []

        for chat in chats:
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
                    "source": "codex",
                    "preview": self._generate_preview(chat),
                }
            )

        return sessions

    def _extract_from_session_files(
        self, session_titles: Dict[str, str]
    ) -> Dict[str, Dict[str, Any]]:
        """Extract sessions from Codex session files."""
        sessions: Dict[str, Dict[str, Any]] = {}
        sessions_dir = self.history_dir / "sessions"

        if not sessions_dir.exists():
            return sessions

        for session_file in sessions_dir.rglob("*.jsonl"):
            try:
                fallback_session_id = self._extract_session_id_from_filename(
                    session_file.name
                )
                session = self._create_session_template(
                    session_id=fallback_session_id or session_file.stem,
                    project_path=None,
                    title=session_titles.get(fallback_session_id or session_file.stem),
                    source_kind="session",
                )
                self._track_source_file(session, session_file)

                with open(session_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError as exc:
                            self.logger.warning(
                                "Invalid JSON in session file %s line %s: %s",
                                session_file,
                                line_num,
                                exc,
                            )
                            continue

                        self._process_session_record(record, session, session_file)

                actual_session_id = session.get("session_id") or fallback_session_id
                if not actual_session_id:
                    continue

                if actual_session_id in session_titles:
                    session["metadata"]["thread_name"] = session_titles[actual_session_id]
                    session["session"]["title"] = session_titles[actual_session_id]
                else:
                    session["session"]["title"] = (
                        f"Codex session {actual_session_id[:8]}"
                    )

                if session["messages"]:
                    sessions[actual_session_id] = session
            except Exception as exc:
                self.logger.warning(
                    f"Error processing session file {session_file}: {exc}"
                )
                continue

        return sessions

    def _extract_from_history_jsonl(
        self,
        existing_session_ids: Optional[set] = None,
        session_titles: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Extract fallback sessions from history.jsonl."""
        sessions: Dict[str, Dict[str, Any]] = {}
        history_file = self.history_dir / "history.jsonl"
        existing_session_ids = existing_session_ids or set()
        session_titles = session_titles or {}

        if not history_file.exists():
            return sessions

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as exc:
                        self.logger.warning(
                            "Invalid JSON in history.jsonl line %s: %s", line_num, exc
                        )
                        continue

                    session_id = entry.get("session_id", f"history_{line_num}")
                    if session_id in existing_session_ids:
                        continue

                    if session_id not in sessions:
                        sessions[session_id] = self._create_session_template(
                            session_id=session_id,
                            project_path=None,
                            title=session_titles.get(session_id),
                            source_kind="history",
                        )
                        sessions[session_id]["metadata"]["fallback_only"] = True

                    text = entry.get("text", "")
                    if not text:
                        continue

                    sessions[session_id]["messages"].append(
                        {
                            "role": "user",
                            "content": text,
                            "timestamp": entry.get("ts"),
                            "source": "history.jsonl",
                        }
                    )
                    self._update_session_timestamps(
                        sessions[session_id], entry.get("ts")
                    )
        except Exception as exc:
            self.logger.warning(f"Error reading history.jsonl: {exc}")

        return sessions

    def _extract_from_log_files(self, project_path: str) -> Dict[str, Dict[str, Any]]:
        """Extract project-related synthetic sessions from log files."""
        sessions: Dict[str, Dict[str, Any]] = {}
        log_dir = self.history_dir / "log"

        if not log_dir.exists():
            return sessions

        for log_file in log_dir.glob("*.log"):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()

                if project_path not in log_content:
                    continue

                session_id = f"log_{log_file.stem}"
                session = self._create_session_template(
                    session_id=session_id,
                    project_path=project_path,
                    title=f"Codex log {log_file.stem}",
                    source_kind="log",
                    synthetic=True,
                )
                self._track_source_file(session, log_file)
                timestamp = int(datetime.now().timestamp())
                session["messages"].append(
                    {
                        "role": "system",
                        "content": f"Log entries related to project:\n{log_content}",
                        "timestamp": timestamp,
                        "source": str(log_file),
                    }
                )
                self._update_session_timestamps(session, timestamp)
                sessions[session_id] = session
            except Exception as exc:
                self.logger.warning(f"Error processing log file {log_file}: {exc}")

        return sessions

    def _extract_from_config(self, project_path: str) -> Dict[str, Dict[str, Any]]:
        """Extract project-related synthetic session from config."""
        sessions: Dict[str, Dict[str, Any]] = {}
        config_file = self.history_dir / "config.toml"

        if not config_file.exists():
            return sessions

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config_content = f.read()

            if project_path not in config_content:
                return sessions

            session_id = "config_project"
            session = self._create_session_template(
                session_id=session_id,
                project_path=project_path,
                title="Codex project config",
                source_kind="config",
                synthetic=True,
            )
            self._track_source_file(session, config_file)
            timestamp = int(datetime.now().timestamp())
            session["messages"].append(
                {
                    "role": "system",
                    "content": f"Project configuration:\n{config_content}",
                    "timestamp": timestamp,
                    "source": "config.toml",
                }
            )
            self._update_session_timestamps(session, timestamp)
            sessions[session_id] = session
        except Exception as exc:
            self.logger.warning(f"Error reading config file: {exc}")

        return sessions

    def _load_session_titles(self) -> Dict[str, str]:
        """Load session titles from session_index.jsonl if available."""
        titles: Dict[str, str] = {}
        index_file = self.history_dir / "session_index.jsonl"

        if not index_file.exists():
            return titles

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as exc:
                        self.logger.warning(
                            "Invalid JSON in session_index.jsonl line %s: %s",
                            line_num,
                            exc,
                        )
                        continue

                    session_id = entry.get("id")
                    thread_name = entry.get("thread_name")
                    if session_id and thread_name:
                        titles[session_id] = thread_name
        except Exception as exc:
            self.logger.warning(f"Error reading session_index.jsonl: {exc}")

        return titles

    def _create_session_template(
        self,
        session_id: str,
        project_path: Optional[str],
        title: Optional[str] = None,
        source_kind: str = "session",
        synthetic: bool = False,
    ) -> Dict[str, Any]:
        """Create a template for a new session."""
        project_root = project_path or "/"
        project_name = (
            extract_project_name_from_path(project_root)
            if project_path
            else "Unknown Project"
        )
        session_title = title or f"Codex session {session_id[:8]}"

        return {
            "session_id": session_id,
            "messages": [],
            "project": {
                "name": project_name,
                "rootPath": project_root,
            },
            "session": {
                "sessionId": session_id,
                "title": session_title,
                "createdAt": None,
                "lastUpdatedAt": None,
            },
            "metadata": {
                "source_files": [],
                "created_at": None,
                "last_updated": None,
                "codex_path": project_path,
                "extractor_version": "2.0",
                "source_kind": source_kind,
                "synthetic": synthetic,
            },
        }

    def _process_session_record(
        self, record: Dict[str, Any], session: Dict[str, Any], file_path: pathlib.Path
    ) -> None:
        """Process a single record from a session file."""
        record_type = record.get("type")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        if record_type == "session_meta":
            self._apply_session_meta(record, payload, session)
            return

        if record_type == "turn_context":
            self._apply_turn_context(payload, session)
            return

        if record_type != "response_item":
            return

        payload_type = payload.get("type")
        timestamp = record.get("timestamp")

        if payload_type == "message":
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                return

            text_content = self._extract_text_content(payload.get("content"))
            if not text_content:
                return

            session["messages"].append(
                {
                    "role": role,
                    "content": text_content,
                    "timestamp": timestamp,
                    "source": str(file_path),
                }
            )
            self._update_session_timestamps(session, timestamp)
            return

        if payload_type == "function_call":
            self._append_tool_message(
                session=session,
                role="assistant",
                heading=f"Function Call: {payload.get('name', 'unknown')}",
                body=self._format_block(payload.get("arguments"), default_language="json"),
                timestamp=timestamp,
                source=str(file_path),
            )
            return

        if payload_type == "function_call_output":
            self._append_tool_message(
                session=session,
                role="system",
                heading=f"Function Output: {payload.get('call_id', 'unknown')}",
                body=self._format_block(payload.get("output")),
                timestamp=timestamp,
                source=str(file_path),
            )
            return

        if payload_type == "custom_tool_call":
            self._append_tool_message(
                session=session,
                role="assistant",
                heading=f"Tool Call: {payload.get('name', 'unknown')}",
                body=self._format_block(payload.get("input")),
                timestamp=timestamp,
                source=str(file_path),
            )
            return

        if payload_type == "custom_tool_call_output":
            self._append_tool_message(
                session=session,
                role="system",
                heading=f"Tool Output: {payload.get('call_id', 'unknown')}",
                body=self._format_block(payload.get("output")),
                timestamp=timestamp,
                source=str(file_path),
            )
            return

        if payload_type == "web_search_call":
            self._append_tool_message(
                session=session,
                role="assistant",
                heading="Web Search",
                body=self._format_block(payload.get("action"), default_language="json"),
                timestamp=timestamp,
                source=str(file_path),
            )

    def _apply_session_meta(
        self, record: Dict[str, Any], payload: Dict[str, Any], session: Dict[str, Any]
    ) -> None:
        """Apply session metadata from session_meta."""
        session_id = payload.get("id")
        if session_id:
            session["session_id"] = session_id
            session["session"]["sessionId"] = session_id

        cwd = payload.get("cwd")
        if cwd:
            session["project"]["rootPath"] = cwd
            session["project"]["name"] = extract_project_name_from_path(cwd)
            session["metadata"]["codex_path"] = cwd

        if payload.get("timestamp"):
            self._update_session_timestamps(session, payload.get("timestamp"))
        elif record.get("timestamp"):
            self._update_session_timestamps(session, record.get("timestamp"))

        if payload.get("cli_version"):
            session["metadata"]["cli_version"] = payload.get("cli_version")
        if payload.get("source"):
            session["metadata"]["codex_source"] = payload.get("source")
        if payload.get("model_provider"):
            session["metadata"]["model_provider"] = payload.get("model_provider")

    def _apply_turn_context(
        self, payload: Dict[str, Any], session: Dict[str, Any]
    ) -> None:
        """Apply useful metadata from turn_context when available."""
        cwd = payload.get("cwd")
        if cwd and session["project"]["rootPath"] == "/":
            session["project"]["rootPath"] = cwd
            session["project"]["name"] = extract_project_name_from_path(cwd)
            session["metadata"]["codex_path"] = cwd

    def _append_tool_message(
        self,
        session: Dict[str, Any],
        role: str,
        heading: str,
        body: str,
        timestamp: Optional[Any],
        source: str,
    ) -> None:
        """Append a tool-related message and keep timestamps in sync."""
        session["messages"].append(
            {
                "role": role,
                "content": f"**{heading}**\n{body}",
                "timestamp": timestamp,
                "source": source,
            }
        )
        self._update_session_timestamps(session, timestamp)

    def _track_source_file(
        self, session: Dict[str, Any], file_path: pathlib.Path
    ) -> None:
        """Track source files for session metadata."""
        source_file = str(file_path)
        if source_file not in session["metadata"]["source_files"]:
            session["metadata"]["source_files"].append(source_file)

    def _extract_session_id_from_filename(self, filename: str) -> Optional[str]:
        """Extract session ID from filename."""
        match = re.search(
            r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\.jsonl$",
            filename,
        )
        if match:
            return match.group(1)
        return None

    def _extract_text_content(self, content: Any) -> str:
        """Extract text from Codex content items."""
        if isinstance(content, str):
            return content.strip()

        if not isinstance(content, list):
            return ""

        parts: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"input_text", "output_text"} and item.get("text"):
                parts.append(str(item["text"]))

        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()

    def _format_block(self, value: Any, default_language: str = "") -> str:
        """Format tool payloads inside fenced code blocks."""
        text = self._stringify_value(value)
        language = default_language
        if not language and self._looks_like_json(text):
            language = "json"

        if language:
            return f"```{language}\n{text}\n```"
        return f"```\n{text}\n```"

    def _stringify_value(self, value: Any) -> str:
        """Convert arbitrary data into readable text."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    def _looks_like_json(self, value: str) -> bool:
        """Check whether a string looks like JSON."""
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

    def _update_session_timestamps(
        self, session: Dict[str, Any], timestamp_value: Optional[Any]
    ) -> None:
        """Update session timestamps from a raw timestamp value."""
        timestamp = self._parse_timestamp(timestamp_value)
        if timestamp is None:
            return

        if session["metadata"]["created_at"] is None:
            session["metadata"]["created_at"] = timestamp
            session["session"]["createdAt"] = timestamp * 1000

        session["metadata"]["last_updated"] = timestamp
        session["session"]["lastUpdatedAt"] = timestamp * 1000

    def _parse_timestamp(self, timestamp_value: Optional[Any]) -> Optional[int]:
        """Parse timestamp values to Unix seconds."""
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

    def _generate_preview(self, chat: Dict[str, Any]) -> str:
        """Generate a preview of the chat session."""
        if not chat["messages"]:
            return "No messages"

        thread_name = chat.get("metadata", {}).get("thread_name")
        if thread_name:
            return thread_name

        for message in chat["messages"]:
            if message["role"] == "user":
                content = message["content"].replace("\n", " ")
                if len(content) > 100:
                    content = content[:100] + "..."
                return content

        return chat.get("session", {}).get("title", "Codex session")
