"""
Windsurf chat history extractor.
"""

import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, unquote

from ..core.extractors import BaseExtractor
from ..utils.paths import (
    extract_project_name_from_path,
    get_project_name,
    get_windsurf_app_root,
    get_windsurf_storage_root,
)


WINDSURF_EXTENSION_BUNDLE = (
    Path("/Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/dist/extension.js")
)

WINDSURF_CACHE_DECODE_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const { TextDecoder, TextEncoder } = require('util');

function loadWebpackRequire(extensionPath) {
  let code = fs.readFileSync(extensionPath, 'utf8');
  const marker =
    'var __webpack_exports__=__webpack_require__(27015),__webpack_export_target__=exports;';
  const idx = code.lastIndexOf(marker);
  if (idx === -1) {
    throw new Error('windsurf extension bundle marker not found');
  }
  code =
    code.slice(0, idx) + 'globalThis.__windsurf_require = __webpack_require__;})();';
  const context = {
    exports: {},
    module: { exports: {} },
    require,
    process,
    Buffer,
    TextDecoder,
    TextEncoder,
    Uint8Array,
    ArrayBuffer,
    DataView,
    setTimeout,
    clearTimeout,
    globalThis: {},
  };
  context.globalThis = context;
  vm.runInNewContext(code, context, {
    filename: 'windsurf-extension.js',
    timeout: 20000,
  });
  return context.globalThis.__windsurf_require;
}

function decodeWorkspace(requireFn, workspace) {
  const msgs = requireFn(29076);
  const cortex = requireFn(99124);
  const result = {
    workspace_id: workspace.workspace_id,
    trajectory_summaries: {},
    active_trajectory: null,
  };

  if (workspace.summary_b64) {
    const summaryBuf = Buffer.from(workspace.summary_b64, 'base64');
    const summaryMsg = msgs.GetAllCascadeTrajectoriesResponse.fromBinary(summaryBuf);
    const summaryJson = summaryMsg.toJson({ emitDefaultValues: false });
    result.trajectory_summaries = summaryJson.trajectorySummaries || {};
  }

  if (workspace.active_b64) {
    const activeBuf = Buffer.from(workspace.active_b64, 'base64');
    const activeMsg = cortex.CascadeState.fromBinary(activeBuf);
    result.active_trajectory = activeMsg.toJson({ emitDefaultValues: false });
  }

  return result;
}

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const requireFn = loadWebpackRequire(input.extension_bundle_path);
const decoded = {
  workspaces: input.workspaces.map((workspace) => decodeWorkspace(requireFn, workspace)),
};
process.stdout.write(JSON.stringify(decoded));
"""


class WindsurfExtractor(BaseExtractor):
    """Extractor for Windsurf chat history."""

    def __init__(self):
        super().__init__("windsurf")
        self.app_root = get_windsurf_app_root()
        self.storage_root = get_windsurf_storage_root()

    def extract_chats(self) -> List[Dict[str, Any]]:
        """Extract all chat data from Windsurf."""
        if not self.storage_root.exists() and not self.app_root.exists():
            self.logger.debug(f"No Windsurf storage found at: {self.storage_root}")
            return []

        workspace_map = self._load_workspace_map()
        chats: List[Dict[str, Any]] = []
        cached_state = self._load_cached_state()

        chats.extend(self._create_chats_from_cache(cached_state, workspace_map))

        for session_file in self._list_session_files():
            session_data = self._read_json_file(session_file)
            if not session_data:
                continue

            chat = self._create_chat(session_data, session_file, workspace_map)
            if chat and chat["messages"]:
                chats.append(chat)

        for unsupported_file in self._list_unsupported_binary_files():
            self.logger.debug(
                "Skipping unsupported Windsurf binary session file: %s",
                unsupported_file,
            )

        deduped_chats = self._dedupe_chats(chats)
        deduped_chats.sort(
            key=lambda chat: chat["session"].get("lastUpdatedAt") or 0,
            reverse=True,
        )
        self.logger.info(f"Extracted {len(deduped_chats)} Windsurf chat sessions")
        return deduped_chats

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List Windsurf chat sessions for the current workspace."""
        sessions = []
        current_project = get_project_name().lower()
        cached_state = self._load_cached_state()
        active_chats = {chat["session_id"]: chat for chat in self.extract_chats()}

        if cached_state.get("workspaces"):
            for workspace_state in cached_state.get("workspaces", []):
                workspace_id = str(workspace_state.get("workspace_id") or "unknown")
                for session_id, summary in workspace_state.get("trajectory_summaries", {}).items():
                    project_root = self._extract_project_root_from_summary(summary) or ""
                    project_name = extract_project_name_from_path(project_root) if project_root else "Unknown Project"
                    if (
                        current_project not in project_name.lower()
                        and project_name.lower() not in current_project
                    ):
                        continue

                    created_at = (
                        self._coerce_iso_timestamp_ms(summary.get("createdTime"))
                        or self._coerce_iso_timestamp_ms(summary.get("lastUserInputTime"))
                        or self._coerce_iso_timestamp_ms(summary.get("lastModifiedTime"))
                    )
                    date_str = self._format_session_date(created_at)
                    active_chat = active_chats.get(session_id)
                    preview = str(summary.get("summary") or "No messages")
                    message_count = 0
                    if active_chat:
                        preview = self._build_preview(active_chat.get("messages", []), preview)
                        message_count = len(active_chat.get("messages", []))

                    sessions.append(
                        {
                            "session_id": session_id[:8],
                            "project": project_name,
                            "date": date_str,
                            "message_count": message_count,
                            "preview": preview,
                            "workspace_id": workspace_id,
                        }
                    )

            return sessions

        for chat in active_chats.values():
            project_name = chat.get("project", {}).get("name", "Unknown Project")
            if (
                current_project not in project_name.lower()
                and project_name.lower() not in current_project
            ):
                continue

            created_at = chat.get("session", {}).get("createdAt")
            date_str = self._format_session_date(created_at)
            messages = chat.get("messages", [])
            preview = self._build_preview(messages)

            sessions.append(
                {
                    "session_id": chat.get("session_id", "unknown")[:8],
                    "project": project_name,
                    "date": date_str,
                    "message_count": len(messages),
                    "preview": preview,
                    "workspace_id": chat.get("workspace_id", "unknown"),
                }
            )

        return sessions

    def _load_cached_state(self) -> Dict[str, Any]:
        """Load decoded Windsurf cache state from either a fixture or local storage."""
        fixture_path = self.storage_root / "cache_state.json"
        if fixture_path.exists():
            data = self._read_json_file(fixture_path)
            if data:
                return data

        global_storage_db = self.app_root / "User" / "globalStorage" / "state.vscdb"
        if not global_storage_db.exists():
            return {}

        payloads: Dict[str, Dict[str, str]] = {}
        try:
            with sqlite3.connect(global_storage_db) as connection:
                row = connection.execute(
                    "select value from ItemTable where key = ?",
                    ("codeium.windsurf",),
                ).fetchone()
        except Exception as e:
            self.logger.debug("Failed to read Windsurf global storage database %s: %s", global_storage_db, e)
            return {}

        if not row or not row[0]:
            return {}

        try:
            storage_data = json.loads(row[0])
        except Exception as e:
            self.logger.debug("Failed to parse Windsurf global storage JSON: %s", e)
            return {}

        for key, value in storage_data.items():
            if not isinstance(value, str) or not value:
                continue
            summary_match = re.match(r"^windsurf\.state\.cachedTrajectorySummaries:(.+)$", key)
            active_match = re.match(r"^windsurf\.state\.cachedActiveTrajectory:(.+)$", key)
            if summary_match:
                payloads.setdefault(summary_match.group(1), {})["summary_b64"] = value
            elif active_match:
                payloads.setdefault(active_match.group(1), {})["active_b64"] = value

        if not payloads:
            return {}

        return self._decode_cached_payloads(payloads)

    def _decode_cached_payloads(self, payloads: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
        """Decode protobuf cache payloads using Windsurf's own bundled protobuf definitions."""
        node_binary = shutil.which("node")
        if not node_binary:
            self.logger.debug("Node.js is required to decode Windsurf cached trajectories")
            return {}

        if not WINDSURF_EXTENSION_BUNDLE.exists():
            self.logger.debug("Windsurf extension bundle not found at %s", WINDSURF_EXTENSION_BUNDLE)
            return {}

        request_payload = {
            "extension_bundle_path": str(WINDSURF_EXTENSION_BUNDLE),
            "workspaces": [
                {
                    "workspace_id": workspace_id,
                    "summary_b64": values.get("summary_b64", ""),
                    "active_b64": values.get("active_b64", ""),
                }
                for workspace_id, values in payloads.items()
            ],
        }

        try:
            result = subprocess.run(
                [node_binary, "-e", WINDSURF_CACHE_DECODE_SCRIPT],
                input=json.dumps(request_payload),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as e:
            self.logger.debug("Failed to run Windsurf cache decoder: %s", e)
            return {}

        if result.returncode != 0:
            self.logger.debug("Windsurf cache decoder failed: %s", result.stderr.strip())
            return {}

        try:
            return json.loads(result.stdout)
        except Exception as e:
            self.logger.debug("Failed to parse Windsurf cache decoder output: %s", e)
            return {}

    def _create_chats_from_cache(
        self,
        cached_state: Dict[str, Any],
        workspace_map: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Create chat exports from decoded Windsurf cache state."""
        chats: List[Dict[str, Any]] = []
        for workspace_state in cached_state.get("workspaces", []):
            active_trajectory = workspace_state.get("active_trajectory")
            if not isinstance(active_trajectory, dict):
                continue

            session_id = str(active_trajectory.get("cascadeId") or "").strip()
            if not session_id:
                continue

            summaries = workspace_state.get("trajectory_summaries", {})
            summary = summaries.get(session_id, {}) if isinstance(summaries, dict) else {}
            chat = self._create_chat_from_active_trajectory(
                workspace_id=str(workspace_state.get("workspace_id") or "unknown"),
                active_trajectory=active_trajectory,
                summary=summary,
                workspace_map=workspace_map,
            )
            if chat and chat["messages"]:
                chats.append(chat)

        return chats

    def _create_chat_from_active_trajectory(
        self,
        workspace_id: str,
        active_trajectory: Dict[str, Any],
        summary: Dict[str, Any],
        workspace_map: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        """Normalize a cached active trajectory into the export format."""
        session_id = str(active_trajectory.get("cascadeId") or "").strip()
        if not session_id:
            return None

        messages = self._normalize_trajectory_messages(active_trajectory)
        if not messages:
            return None

        project_root = self._extract_project_root_from_summary(summary)
        workspace_project = workspace_map.get(workspace_id, {})
        if not project_root:
            project_root = workspace_project.get("rootPath", "")
        if not project_root:
            project_root = "/"

        project_name = workspace_project.get("name") or extract_project_name_from_path(project_root)
        title = str(summary.get("summary") or f"Windsurf session {session_id[:8]}")
        created_at = self._coerce_iso_timestamp_ms(summary.get("createdTime"))
        updated_at = self._coerce_iso_timestamp_ms(summary.get("lastModifiedTime"))

        if created_at is None and messages:
            created_at = self._coerce_timestamp_ms(messages[0].get("timestamp"))
        if updated_at is None and messages:
            updated_at = self._coerce_timestamp_ms(messages[-1].get("timestamp"))
        if created_at is None:
            created_at = updated_at
        if updated_at is None:
            updated_at = created_at

        return {
            "session_id": session_id,
            "workspace_id": workspace_id or "unknown",
            "project": {
                "name": project_name,
                "rootPath": project_root,
            },
            "session": {
                "sessionId": session_id,
                "title": title,
                "createdAt": created_at,
                "lastUpdatedAt": updated_at,
            },
            "messages": messages,
            "metadata": {
                "source_files": [
                    str(self.app_root / "User" / "globalStorage" / "state.vscdb"),
                    str(self.storage_root / "cascade" / f"{session_id}.pb"),
                ],
                "storage_kind": "windsurf_cache",
                "storage_path": str(self.app_root / "User" / "globalStorage" / "state.vscdb"),
                "workspace_id": workspace_id or "unknown",
                "trajectory_type": active_trajectory.get("trajectory", {}).get("trajectoryType"),
                "created_at": self._to_unix_seconds(created_at),
                "last_updated": self._to_unix_seconds(updated_at),
            },
        }

    def _list_session_files(self) -> List[Path]:
        """List Windsurf session files that are directly readable as JSON."""
        patterns = [
            self.storage_root / "cascade" / "*.json",
            self.storage_root / "sessions" / "*.json",
            self.storage_root / "exports" / "*.json",
        ]
        files: List[Path] = []
        for pattern in patterns:
            files.extend(sorted(pattern.parent.glob(pattern.name)))
        return files

    def _list_unsupported_binary_files(self) -> List[Path]:
        """List Windsurf binary session files we currently cannot decode safely."""
        files: List[Path] = []
        for directory in [self.storage_root / "cascade", self.storage_root / "implicit"]:
            if not directory.exists():
                continue
            files.extend(sorted(directory.glob("*.pb")))
        return files

    def _load_workspace_map(self) -> Dict[str, Dict[str, str]]:
        """Load workspace ID to project metadata mapping."""
        workspace_storage = self.app_root / "User" / "workspaceStorage"
        if not workspace_storage.exists():
            return {}

        workspace_map: Dict[str, Dict[str, str]] = {}
        for workspace_dir in workspace_storage.iterdir():
            workspace_json = workspace_dir / "workspace.json"
            if not workspace_json.exists():
                continue

            data = self._read_json_file(workspace_json)
            if not data:
                continue

            folder_uri = str(data.get("folder") or "")
            root_path = self._folder_uri_to_path(folder_uri)
            if not root_path:
                continue

            workspace_map[workspace_dir.name] = {
                "name": extract_project_name_from_path(root_path),
                "rootPath": root_path,
            }

        return workspace_map

    def _create_chat(
        self,
        session_data: Dict[str, Any],
        session_file: Path,
        workspace_map: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        """Create a normalized Windsurf chat object."""
        messages = self._normalize_messages(session_data.get("messages", []))
        if not messages:
            return None

        session_id = str(session_data.get("session_id") or session_data.get("id") or session_file.stem)
        workspace_id = str(session_data.get("workspace_id") or "")
        project_root = str(session_data.get("project_root") or "")
        project_name = str(session_data.get("project_name") or "")

        workspace_project = workspace_map.get(workspace_id, {})
        if not project_root:
            project_root = workspace_project.get("rootPath", "")
        if not project_name:
            project_name = workspace_project.get("name", "")

        if not project_root:
            project_root = "/"
        if not project_name:
            project_name = extract_project_name_from_path(project_root)

        created_at = self._coerce_timestamp_ms(session_data.get("created_at"))
        updated_at = self._coerce_timestamp_ms(session_data.get("updated_at"))
        if created_at is None:
            created_at = updated_at
        if updated_at is None:
            updated_at = created_at

        title = str(session_data.get("title") or f"Windsurf session {session_id[:8]}")

        return {
            "session_id": session_id,
            "workspace_id": workspace_id or "unknown",
            "project": {
                "name": project_name,
                "rootPath": project_root,
            },
            "session": {
                "sessionId": session_id,
                "title": title,
                "createdAt": created_at,
                "lastUpdatedAt": updated_at,
            },
            "messages": messages,
            "metadata": {
                "source_files": [str(session_file)],
                "storage_kind": str(session_data.get("storage_kind") or "windsurf_json"),
                "storage_path": str(session_file),
                "workspace_id": workspace_id or "unknown",
                "created_at": self._to_unix_seconds(created_at),
                "last_updated": self._to_unix_seconds(updated_at),
            },
        }

    def _normalize_messages(self, raw_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize Windsurf messages into the export format."""
        messages: List[Dict[str, Any]] = []
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue

            role = str(raw_message.get("role") or "").strip().lower()
            content = str(raw_message.get("content") or "").strip()
            if not content or role not in {"user", "assistant", "system"}:
                continue

            timestamp = self._coerce_timestamp_seconds(raw_message.get("timestamp"))
            messages.append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                }
            )

        return messages

    def _normalize_trajectory_messages(
        self, active_trajectory: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Normalize cached active trajectory steps into user/assistant messages."""
        messages: List[Dict[str, Any]] = []
        trajectory = active_trajectory.get("trajectory", {})
        steps = trajectory.get("steps", []) if isinstance(trajectory, dict) else []

        for step in steps:
            if not isinstance(step, dict):
                continue

            step_type = str(step.get("type") or "").strip()
            metadata = step.get("metadata", {}) if isinstance(step.get("metadata"), dict) else {}
            timestamp = self._coerce_iso_timestamp_seconds(
                metadata.get("viewableAt")
                or metadata.get("createdAt")
                or metadata.get("completedAt")
            )

            if step_type == "CORTEX_STEP_TYPE_USER_INPUT":
                user_input = step.get("userInput", {}) if isinstance(step.get("userInput"), dict) else {}
                content = str(user_input.get("userResponse") or "").strip()
                if not content:
                    items = user_input.get("items", [])
                    item_texts = [
                        str(item.get("text") or "").strip()
                        for item in items
                        if isinstance(item, dict) and str(item.get("text") or "").strip()
                    ]
                    content = "\n".join(item_texts).strip()
                if content:
                    messages.append(
                        {
                            "role": "user",
                            "content": content,
                            "timestamp": timestamp,
                        }
                    )
                continue

            if step_type == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
                planner_response = (
                    step.get("plannerResponse", {})
                    if isinstance(step.get("plannerResponse"), dict)
                    else {}
                )
                content = str(
                    planner_response.get("modifiedResponse")
                    or planner_response.get("response")
                    or ""
                ).strip()
                if content:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": content,
                            "timestamp": timestamp,
                        }
                    )

        return messages

    def _folder_uri_to_path(self, folder_uri: str) -> str:
        """Convert a file:/// URI into a filesystem path."""
        if not folder_uri.startswith("file://"):
            return ""

        parsed = urlparse(folder_uri)
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            path = f"//{parsed.netloc}{path}"
        return path or ""

    def _read_json_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read a JSON file safely."""
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.debug(f"Failed to read Windsurf JSON file {path}: {e}")
            return None

    def _extract_project_root_from_summary(self, summary: Dict[str, Any]) -> str:
        """Extract project root path from a decoded trajectory summary."""
        workspaces = summary.get("workspaces", []) if isinstance(summary, dict) else []
        for workspace in workspaces:
            if not isinstance(workspace, dict):
                continue
            folder_uri = str(
                workspace.get("workspaceFolderAbsoluteUri")
                or workspace.get("gitRootAbsoluteUri")
                or ""
            )
            project_root = self._folder_uri_to_path(folder_uri)
            if project_root:
                return project_root
        return ""

    def _format_session_date(self, created_at: Optional[int]) -> str:
        """Format a session timestamp for list output."""
        if not created_at:
            return "Unknown date"
        try:
            timestamp = created_at / 1000 if created_at > 1e10 else created_at
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "Unknown date"

    def _build_preview(self, messages: List[Dict[str, Any]], fallback: str = "No messages") -> str:
        """Build a short session preview."""
        if messages:
            preview = str(messages[0].get("content") or "").replace("\n", " ").strip()
            if preview:
                return preview[:60] + "..." if len(preview) > 60 else preview
        fallback_preview = str(fallback or "No messages").replace("\n", " ").strip()
        return fallback_preview[:60] + "..." if len(fallback_preview) > 60 else fallback_preview

    def _dedupe_chats(self, chats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate chats by session ID, preferring cache-backed conversations."""
        deduped: Dict[str, Dict[str, Any]] = {}
        for chat in chats:
            session_id = str(chat.get("session_id") or "")
            if not session_id:
                continue
            existing = deduped.get(session_id)
            if not existing:
                deduped[session_id] = chat
                continue

            existing_kind = str(existing.get("metadata", {}).get("storage_kind") or "")
            new_kind = str(chat.get("metadata", {}).get("storage_kind") or "")
            if new_kind == "windsurf_cache" and existing_kind != "windsurf_cache":
                deduped[session_id] = chat
                continue
            if len(chat.get("messages", [])) > len(existing.get("messages", [])):
                deduped[session_id] = chat

        return list(deduped.values())

    def _coerce_timestamp_ms(self, value: Any) -> Optional[int]:
        """Convert timestamps to integer milliseconds."""
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if number <= 0:
            return None
        if number < 1e10:
            number *= 1000
        return int(number)

    def _coerce_timestamp_seconds(self, value: Any) -> Optional[int]:
        """Convert timestamps to integer seconds."""
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if number <= 0:
            return None
        if number > 1e10:
            number /= 1000
        return int(number)

    def _to_unix_seconds(self, value: Optional[int]) -> Optional[int]:
        """Convert integer milliseconds to integer seconds."""
        if value is None:
            return None
        return int(value / 1000 if value > 1e10 else value)

    def _coerce_iso_timestamp_ms(self, value: Any) -> Optional[int]:
        """Convert an ISO-8601 timestamp into integer milliseconds."""
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except Exception:
            return None

    def _coerce_iso_timestamp_seconds(self, value: Any) -> Optional[int]:
        """Convert an ISO-8601 timestamp into integer seconds."""
        timestamp_ms = self._coerce_iso_timestamp_ms(value)
        return self._to_unix_seconds(timestamp_ms)
