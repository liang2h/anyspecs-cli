"""
Windsurf chat history extractor.
"""

import json
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

from ..core.extractors import BaseExtractor
from ..utils.paths import (
    extract_project_name_from_path,
    get_project_name,
    get_windsurf_app_root,
    get_windsurf_storage_root,
    resolve_windsurf_app_root,
    resolve_windsurf_extension_bundle_path,
    resolve_windsurf_storage_root,
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
    URL,
    URLSearchParams,
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


WINDSURF_TRAJECTORY_FETCH_SCRIPT = r"""
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
    URL,
    URLSearchParams,
    AbortController,
    AbortSignal,
    fetch,
    Headers,
    Request,
    Response,
    ReadableStream,
    TransformStream,
    performance,
    globalThis: {},
  };
  context.globalThis = context;
  vm.runInNewContext(code, context, {
    filename: 'windsurf-extension.js',
    timeout: 20000,
  });
  return context.globalThis.__windsurf_require;
}

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const requireFn = loadWebpackRequire(input.extension_bundle_path);
  const msgs = requireFn(29076);
  const results = {};
  const errors = {};
  const endpoint = `${input.base_url}/exa.language_server_pb.LanguageServerService/GetCascadeTrajectory`;

  for (const sessionId of input.session_ids || []) {
    try {
      const request = new msgs.GetCascadeTrajectoryRequest({ cascadeId: sessionId });
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/proto',
          'Accept': 'application/proto',
          'Connect-Protocol-Version': '1',
          'x-codeium-csrf-token': input.csrf_token,
        },
        body: Buffer.from(request.toBinary()),
      });

      const rawBody = new Uint8Array(await response.arrayBuffer());
      if (!response.ok) {
        errors[sessionId] = `language server returned ${response.status} ${response.statusText}`;
        continue;
      }

      const decoded = msgs.GetCascadeTrajectoryResponse.fromBinary(rawBody);
      results[sessionId] = decoded.toJson({ emitDefaultValues: false });
    } catch (error) {
      errors[sessionId] = error && error.message ? error.message : String(error);
    }
  }

  process.stdout.write(JSON.stringify({ trajectories: results, errors }));
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""


class WindsurfExtractor(BaseExtractor):
    """Extractor for Windsurf chat history."""

    def __init__(self):
        super().__init__("windsurf")
        resolved_app_root, app_root_source = resolve_windsurf_app_root()
        resolved_storage_root, storage_root_source = resolve_windsurf_storage_root()
        resolved_bundle_path, bundle_source = resolve_windsurf_extension_bundle_path()

        self.app_root = resolved_app_root or self._default_windsurf_app_root()
        self.storage_root = resolved_storage_root or self._default_windsurf_storage_root()
        self.extension_bundle_path = resolved_bundle_path
        self.path_resolution = {
            "app_root": app_root_source,
            "storage_root": storage_root_source,
            "extension_bundle_path": bundle_source,
        }
        self.session_decode_errors: Dict[str, str] = {}
        self._last_session_records: Dict[str, Dict[str, Any]] = {}
        self._last_index_context: Optional[Dict[str, Any]] = None
        self._workspace_servers: Dict[str, Dict[str, Any]] = {}
        self._command_scope_active = False

        self.logger.debug(
            "Resolved Windsurf paths: app_root=%s (%s), storage_root=%s (%s), "
            "extension_bundle=%s (%s)",
            self.app_root,
            app_root_source,
            self.storage_root,
            storage_root_source,
            self.extension_bundle_path,
            bundle_source,
        )

    def begin_command_scope(self) -> None:
        """Reset Windsurf runtime state for a single CLI command."""
        self.close_command_scope()
        self._command_scope_active = True

    def close_command_scope(self) -> None:
        """Tear down cached Windsurf language servers for the current CLI command."""
        for workspace_id in list(self._workspace_servers.keys()):
            self._discard_workspace_server(workspace_id)
        self._command_scope_active = False

    def extract_chats(self) -> List[Dict[str, Any]]:
        """Extract all chat data from Windsurf."""
        self.session_decode_errors = {}
        index_context = self.get_index_context()
        return self.extract_chats_for_export(index_context=index_context)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List Windsurf chat sessions for the current workspace."""
        current_project = get_project_name().lower()
        index_context = self.get_index_context()
        session_records = index_context["session_records"]

        sessions: List[Dict[str, Any]] = []
        for record in session_records:
            session_id = record["session_id"]
            project_name = record["project_name"] or "Unknown Project"
            if (
                current_project not in project_name.lower()
                and project_name.lower() not in current_project
            ):
                continue

            active_messages = []
            if record.get("active_trajectory"):
                active_messages = self._normalize_trajectory_messages(record["active_trajectory"])

            preview = self._build_preview(
                active_messages,
                str(record["summary"].get("summary") or "No messages"),
            )
            message_count = len(active_messages) if active_messages else 0

            sessions.append(
                {
                    "session_id": session_id[:8],
                    "project": project_name,
                    "date": self._format_session_date(record["created_at"]),
                    "message_count": message_count,
                    "preview": preview,
                    "workspace_id": record["workspace_id"],
                }
            )

        return sessions

    def get_index_context(self) -> Dict[str, Any]:
        """Build and store the lightweight Windsurf session index context."""
        self.session_decode_errors = {}
        self._last_session_records = {}

        if not self.app_root.exists() and not self.storage_root.exists():
            self.logger.debug(
                "No Windsurf storage found at app_root=%s storage_root=%s",
                self.app_root,
                self.storage_root,
            )
            index_context = {
                "workspace_map": {},
                "cached_state": {},
                "session_records": [],
            }
            self._last_index_context = index_context
            return index_context

        workspace_map = self._load_workspace_map()
        cached_state = self._load_cached_state()
        session_records = self._build_session_records(cached_state, workspace_map)
        self._last_session_records = {record["session_id"]: record for record in session_records}

        index_context = {
            "workspace_map": workspace_map,
            "cached_state": cached_state,
            "session_records": session_records,
        }
        self._last_index_context = index_context
        return index_context

    def build_filter_candidates(
        self,
        index_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Build lightweight chat-like records for CLI filtering without decoding bodies."""
        if index_context is None:
            index_context = self.get_index_context()

        candidates: List[Dict[str, Any]] = []
        for record in index_context["session_records"]:
            candidates.append(
                {
                    "session_id": record["session_id"],
                    "project": {
                        "name": record["project_name"],
                        "rootPath": record["project_root"],
                    },
                    "date": record["created_at"] or record["updated_at"],
                    "metadata": {
                        "workspace_id": record["workspace_id"],
                        "summary": record["summary"],
                        "has_pb": record["pb_path"].exists(),
                        "has_active_fallback": bool(record.get("active_trajectory")),
                    },
                    "source": "windsurf",
                    "messages": [],
                }
            )

        return candidates

    def extract_chats_for_export(
        self,
        session_ids: Optional[List[str]] = None,
        index_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Extract only the requested Windsurf chats, decoding bodies on demand."""
        self.session_decode_errors = {}

        if index_context is None:
            index_context = self.get_index_context()
        else:
            self._last_index_context = index_context
            self._last_session_records = {
                record["session_id"]: record for record in index_context["session_records"]
            }

        workspace_map = index_context["workspace_map"]
        session_records = index_context["session_records"]

        selected_records = session_records
        requested_order: Optional[List[str]] = None
        if session_ids is not None:
            requested_order = list(session_ids)
            allowed_session_ids = set(session_ids)
            selected_records = [
                record for record in session_records if record["session_id"] in allowed_session_ids
            ]

        chats_by_id: Dict[str, Dict[str, Any]] = {}
        unresolved_errors: Dict[str, str] = {}

        allowed_json_session_ids = {record["session_id"] for record in selected_records}
        for chat in self._load_json_chats(workspace_map, allowed_json_session_ids):
            self._store_preferred_chat(chats_by_id, chat)

        trajectories_by_session, trajectory_errors = self._decode_pb_trajectories(selected_records)
        unresolved_errors.update(trajectory_errors)

        for record in selected_records:
            session_id = record["session_id"]
            chat = None

            if session_id in trajectories_by_session:
                chat = self._create_chat_from_trajectory(
                    record=record,
                    trajectory_response=trajectories_by_session[session_id],
                    workspace_map=workspace_map,
                    storage_kind="windsurf_pb",
                )
            elif record.get("active_trajectory"):
                chat = self._create_chat_from_active_trajectory(
                    workspace_id=record["workspace_id"],
                    active_trajectory=record["active_trajectory"],
                    summary=record["summary"],
                    workspace_map=workspace_map,
                    storage_kind="windsurf_cache_active_fallback",
                )
            elif session_id not in unresolved_errors:
                unresolved_errors[session_id] = (
                    f"Windsurf session '{session_id}' was found, but its trajectory "
                    "body could not be decoded. The active-session cache fallback only "
                    "works for the currently open Windsurf session."
                )

            if chat and chat.get("messages"):
                self._store_preferred_chat(chats_by_id, chat)

        for session_id, message in unresolved_errors.items():
            if session_id not in chats_by_id:
                self.session_decode_errors[session_id] = message

        if requested_order is not None:
            chats = [
                chats_by_id[session_id]
                for session_id in requested_order
                if session_id in chats_by_id
            ]
        else:
            chats = list(chats_by_id.values())
            chats.sort(
                key=lambda chat: chat["session"].get("lastUpdatedAt") or 0,
                reverse=True,
            )

        self.logger.info("Extracted %s Windsurf chat sessions", len(chats))
        return chats

    def get_session_export_error(self, session_prefix: str) -> Optional[str]:
        """Return a user-facing export error for a Windsurf session prefix."""
        matches = [
            message
            for session_id, message in self.session_decode_errors.items()
            if session_id.startswith(session_prefix)
        ]
        if matches:
            return matches[0]

        matching_known_sessions = [
            session_id
            for session_id in self._last_session_records.keys()
            if session_id.startswith(session_prefix)
        ]
        if matching_known_sessions:
            return (
                f"Windsurf session '{matching_known_sessions[0]}' was found, but its "
                "trajectory body could not be decoded. The active-session cache fallback "
                "only works for the currently open Windsurf session."
            )
        return None

    def _build_session_records(
        self,
        cached_state: Dict[str, Any],
        workspace_map: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Build a deduplicated session index from cached trajectory summaries."""
        records_by_id: Dict[str, Dict[str, Any]] = {}

        for workspace_state in cached_state.get("workspaces", []):
            workspace_id = str(workspace_state.get("workspace_id") or "unknown")
            active_trajectory = (
                workspace_state.get("active_trajectory")
                if isinstance(workspace_state.get("active_trajectory"), dict)
                else None
            )
            active_session_id = ""
            if active_trajectory:
                active_session_id = str(active_trajectory.get("cascadeId") or "").strip()

            summaries = workspace_state.get("trajectory_summaries", {})
            if not isinstance(summaries, dict):
                summaries = {}

            for session_id, summary in summaries.items():
                if not isinstance(summary, dict):
                    summary = {}

                project_root = self._extract_project_root_from_summary(summary)
                workspace_project = workspace_map.get(workspace_id, {})
                if not project_root:
                    project_root = workspace_project.get("rootPath", "")
                if not project_root:
                    project_root = "/"

                project_name = (
                    workspace_project.get("name")
                    or extract_project_name_from_path(project_root)
                )
                created_at = (
                    self._coerce_iso_timestamp_ms(summary.get("createdTime"))
                    or self._coerce_iso_timestamp_ms(summary.get("lastUserInputTime"))
                    or self._coerce_iso_timestamp_ms(summary.get("lastModifiedTime"))
                )
                updated_at = (
                    self._coerce_iso_timestamp_ms(summary.get("lastModifiedTime"))
                    or self._coerce_iso_timestamp_ms(summary.get("lastUserInputTime"))
                    or created_at
                )

                record = {
                    "session_id": str(session_id),
                    "workspace_id": workspace_id,
                    "summary": summary,
                    "project_root": project_root,
                    "project_name": project_name,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "active_trajectory": active_trajectory
                    if session_id == active_session_id
                    else None,
                    "pb_path": self.storage_root / "cascade" / f"{session_id}.pb",
                    "state_db_path": self.app_root / "User" / "globalStorage" / "state.vscdb",
                }

                existing = records_by_id.get(record["session_id"])
                if existing is None or self._should_replace_session_record(existing, record):
                    records_by_id[record["session_id"]] = record

            if active_trajectory and active_session_id and active_session_id not in records_by_id:
                record = self._build_active_only_record(
                    workspace_id=workspace_id,
                    active_trajectory=active_trajectory,
                    workspace_map=workspace_map,
                )
                if record:
                    records_by_id[active_session_id] = record

        records = list(records_by_id.values())
        records.sort(key=lambda record: record.get("updated_at") or 0, reverse=True)
        return records

    def _build_active_only_record(
        self,
        workspace_id: str,
        active_trajectory: Dict[str, Any],
        workspace_map: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        """Build a fallback session record when only the active trajectory is available."""
        session_id = str(active_trajectory.get("cascadeId") or "").strip()
        if not session_id:
            return None

        workspace_project = workspace_map.get(workspace_id, {})
        project_root = workspace_project.get("rootPath") or "/"
        project_name = workspace_project.get("name") or extract_project_name_from_path(project_root)
        messages = self._normalize_trajectory_messages(active_trajectory)
        created_at = self._coerce_timestamp_ms(messages[0].get("timestamp")) if messages else None
        updated_at = self._coerce_timestamp_ms(messages[-1].get("timestamp")) if messages else None

        return {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "summary": {},
            "project_root": project_root,
            "project_name": project_name,
            "created_at": created_at,
            "updated_at": updated_at or created_at,
            "active_trajectory": active_trajectory,
            "pb_path": self.storage_root / "cascade" / f"{session_id}.pb",
            "state_db_path": self.app_root / "User" / "globalStorage" / "state.vscdb",
        }

    def _should_replace_session_record(
        self,
        existing: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> bool:
        """Choose the preferred session record when summaries duplicate across workspaces."""
        existing_active = existing.get("active_trajectory") is not None
        candidate_active = candidate.get("active_trajectory") is not None
        if candidate_active != existing_active:
            return candidate_active

        existing_root = existing.get("project_root") not in {"", "/"}
        candidate_root = candidate.get("project_root") not in {"", "/"}
        if candidate_root != existing_root:
            return candidate_root

        return (candidate.get("updated_at") or 0) > (existing.get("updated_at") or 0)

    def _decode_pb_trajectories(
        self,
        session_records: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        """Decode historical Windsurf trajectories grouped by workspace."""
        trajectories_by_session: Dict[str, Dict[str, Any]] = {}
        errors_by_session: Dict[str, str] = {}

        records_with_pb = [record for record in session_records if record["pb_path"].exists()]
        if not records_with_pb:
            return trajectories_by_session, errors_by_session

        node_binary = shutil.which("node")
        if not node_binary:
            error_message = "Node.js is required to decode Windsurf trajectory files."
            for record in records_with_pb:
                errors_by_session[record["session_id"]] = error_message
            return trajectories_by_session, errors_by_session

        if not self.extension_bundle_path or not self.extension_bundle_path.exists():
            error_message = (
                "Windsurf extension bundle could not be resolved. Set "
                "ANYSPECS_WINDSURF_EXTENSION_BUNDLE or configure "
                "sources.windsurf.extension_bundle_path."
            )
            for record in records_with_pb:
                errors_by_session[record["session_id"]] = error_message
            return trajectories_by_session, errors_by_session

        binary_path = self._get_language_server_binary()
        if not binary_path:
            error_message = (
                "Windsurf language server binary could not be found next to the "
                "extension bundle."
            )
            for record in records_with_pb:
                errors_by_session[record["session_id"]] = error_message
            return trajectories_by_session, errors_by_session

        records_by_workspace: Dict[str, List[Dict[str, Any]]] = {}
        for record in records_with_pb:
            records_by_workspace.setdefault(record["workspace_id"], []).append(record)

        for workspace_id, records in records_by_workspace.items():
            decoded, errors = self._fetch_workspace_trajectories(
                workspace_id=workspace_id,
                session_ids=[record["session_id"] for record in records],
                binary_path=binary_path,
                node_binary=node_binary,
            )
            trajectories_by_session.update(decoded)
            errors_by_session.update(errors)

        return trajectories_by_session, errors_by_session

    def _fetch_workspace_trajectories(
        self,
        workspace_id: str,
        session_ids: List[str],
        binary_path: Path,
        node_binary: str,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        """Fetch full historical trajectories for one workspace via the local language server."""
        if not session_ids:
            return {}, {}

        for attempt in range(2):
            server_info, error_message, should_close = self.ensure_workspace_server(
                workspace_id=workspace_id,
                binary_path=binary_path,
                node_binary=node_binary,
            )
            if not server_info:
                return {}, {session_id: error_message for session_id in session_ids}

            process = server_info["process"]
            if process.poll() is not None:
                if should_close:
                    self._close_workspace_server(server_info)
                else:
                    self._discard_workspace_server(workspace_id)
                if attempt == 0:
                    continue
                error_message = (
                    f"Windsurf language server exited before handling workspace "
                    f"'{workspace_id}'."
                )
                return {}, {session_id: error_message for session_id in session_ids}

            response: Dict[str, Any] = {}
            process_exited = False
            try:
                request_payload = {
                    "extension_bundle_path": str(self.extension_bundle_path),
                    "base_url": server_info["base_url"],
                    "csrf_token": server_info["csrf_token"],
                    "session_ids": session_ids,
                }
                response = self._run_node_json(
                    node_binary=node_binary,
                    script=WINDSURF_TRAJECTORY_FETCH_SCRIPT,
                    payload=request_payload,
                    error_context="Windsurf trajectory fetch",
                )
                process_exited = process.poll() is not None
            finally:
                if should_close:
                    self._close_workspace_server(server_info)

            if not response:
                if process_exited and attempt == 0:
                    self._discard_workspace_server(workspace_id)
                    continue
                error_message = (
                    "Failed to decode Windsurf historical trajectories via the "
                    "local language server."
                )
                return {}, {session_id: error_message for session_id in session_ids}

            normalized_trajectories = {
                str(session_id): trajectory
                for session_id, trajectory in response.get("trajectories", {}).items()
                if isinstance(trajectory, dict)
            }
            normalized_errors = {
                str(session_id): str(message)
                for session_id, message in response.get("errors", {}).items()
                if message
            }
            return normalized_trajectories, normalized_errors

        error_message = (
            "Failed to decode Windsurf historical trajectories via the local "
            "language server."
        )
        return {}, {session_id: error_message for session_id in session_ids}

    def ensure_workspace_server(
        self,
        workspace_id: str,
        binary_path: Path,
        node_binary: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
        """Return a live language server for a workspace, reusing it within one command."""
        existing = self._workspace_servers.get(workspace_id)
        if existing:
            process = existing["process"]
            if process.poll() is None:
                return existing, None, False
            self._discard_workspace_server(workspace_id)

        server_info, error_message = self._start_workspace_server(
            workspace_id=workspace_id,
            binary_path=binary_path,
            node_binary=node_binary,
        )
        if not server_info:
            return None, error_message, False

        if self._command_scope_active:
            self._workspace_servers[workspace_id] = server_info
            return server_info, None, False

        return server_info, None, True

    def _start_workspace_server(
        self,
        workspace_id: str,
        binary_path: Path,
        node_binary: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Start a new Windsurf language server process for one workspace."""
        csrf_token = f"anyspecs-{uuid.uuid4().hex}"
        server_port = self._reserve_local_port()
        lsp_port = self._reserve_local_port()
        manager_dir = Path(tempfile.mkdtemp(prefix="anyspecs-windsurf-ls-"))
        command = [
            str(binary_path),
            "--server_port",
            str(server_port),
            "--lsp_port",
            str(lsp_port),
            "--workspace_id",
            workspace_id,
            "--codeium_dir",
            str(self.storage_root),
            "--database_dir",
            str(self.storage_root / "database"),
            "--manager_dir",
            str(manager_dir),
            "--csrf_token",
            csrf_token,
            "--verbosity_level",
            "1",
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        listening_port = self._wait_for_language_server_port(
            process=process,
            manager_dir=manager_dir,
            timeout_seconds=20,
        )
        if not listening_port:
            error_message = (
                f"Timed out waiting for Windsurf language server for workspace "
                f"'{workspace_id}'."
            )
            self._close_workspace_server(
                {
                    "process": process,
                    "manager_dir": manager_dir,
                }
            )
            return None, error_message

        return (
            {
                "workspace_id": workspace_id,
                "process": process,
                "listening_port": listening_port,
                "csrf_token": csrf_token,
                "manager_dir": manager_dir,
                "binary_path": binary_path,
                "node_binary": node_binary,
                "base_url": f"http://127.0.0.1:{listening_port}",
            },
            None,
        )

    def _discard_workspace_server(self, workspace_id: str) -> None:
        """Remove a cached workspace server and release its resources."""
        server_info = self._workspace_servers.pop(workspace_id, None)
        if server_info:
            self._close_workspace_server(server_info)

    def _close_workspace_server(self, server_info: Dict[str, Any]) -> None:
        """Stop one workspace server and clean up its manager directory."""
        process = server_info.get("process")
        if process is not None:
            self._stop_language_server(process)

        manager_dir = server_info.get("manager_dir")
        if manager_dir is not None:
            self._cleanup_manager_dir(Path(manager_dir))

    def _wait_for_language_server_port(
        self,
        process: subprocess.Popen,
        manager_dir: Path,
        timeout_seconds: int,
    ) -> Optional[int]:
        """Wait until the Windsurf manager writes the child HTTP port marker file."""
        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            port_file = self._find_language_server_port_file(manager_dir)
            if port_file is not None:
                return int(port_file.name)

            if process.poll() is not None:
                break

            time.sleep(0.25)

        process_exit_code = process.poll()
        stderr_preview = self._read_language_server_stderr_preview(manager_dir)
        self.logger.debug(
            "Windsurf language server did not publish a port "
            "(exit_code=%s, manager_dir=%s, stderr=%s)",
            process_exit_code,
            self._debug_manager_dir_contents(manager_dir),
            stderr_preview,
        )
        return None

    def _find_language_server_port_file(self, manager_dir: Path) -> Optional[Path]:
        """Return the manager port marker file when it appears."""
        try:
            if not manager_dir.exists():
                return None
        except OSError:
            return None

        try:
            entries = list(manager_dir.iterdir())
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None

        candidates = []
        for path in entries:
            try:
                if path.is_file() and path.name.isdigit():
                    candidates.append(path)
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue

        if not candidates:
            return None

        try:
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except (FileNotFoundError, NotADirectoryError, OSError):
            stable_candidates = []
            for path in candidates:
                try:
                    stable_candidates.append((path.stat().st_mtime, path))
                except (FileNotFoundError, NotADirectoryError, OSError):
                    continue
            if not stable_candidates:
                return None
            stable_candidates.sort(key=lambda item: item[0], reverse=True)
            return stable_candidates[0][1]

        return candidates[0]

    def _debug_manager_dir_contents(self, manager_dir: Path) -> str:
        """Build a compact debug string for the Windsurf manager directory."""
        try:
            if not manager_dir.exists():
                return "<missing>"
        except OSError as e:
            return f"<unavailable: {e}>"

        paths: List[str] = []
        try:
            for path in manager_dir.rglob("*"):
                try:
                    paths.append(str(path.relative_to(manager_dir)))
                except (FileNotFoundError, NotADirectoryError, OSError):
                    continue
                if len(paths) >= 20:
                    break
        except (FileNotFoundError, NotADirectoryError, OSError) as e:
            if not paths:
                return f"<unavailable: {e}>"

        return ", ".join(sorted(paths)) if paths else "<empty>"

    def _read_language_server_stderr_preview(
        self,
        manager_dir: Path,
        max_chars: int = 400,
    ) -> str:
        """Read a short preview of the latest language server stderr log."""
        server_outputs_dir = manager_dir / "server_outputs"
        try:
            if not server_outputs_dir.exists():
                return "<missing>"
        except OSError as e:
            return f"<unavailable: {e}>"

        try:
            candidates = sorted(
                [
                    path
                    for path in server_outputs_dir.iterdir()
                    if path.is_file() and path.name.startswith("language_server_stderr")
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except (FileNotFoundError, NotADirectoryError, OSError) as e:
            return f"<unavailable: {e}>"

        if not candidates:
            return "<missing>"

        latest = candidates[0]
        try:
            preview = latest.read_text(encoding="utf-8", errors="replace").strip()
        except (FileNotFoundError, NotADirectoryError, OSError) as e:
            return f"<unavailable: {e}>"

        if not preview:
            return "<empty>"

        preview = preview.replace("\n", "\\n")
        return preview[:max_chars]

    def _stop_language_server(self, process: subprocess.Popen) -> None:
        """Terminate the local Windsurf language server process."""
        if process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _cleanup_manager_dir(self, manager_dir: Path) -> None:
        """Remove the temporary Windsurf manager directory without failing export flow."""
        try:
            if not manager_dir.exists():
                return
        except OSError as e:
            self.logger.debug(
                "Failed to inspect Windsurf manager dir before cleanup %s: %s",
                manager_dir,
                e,
            )
            return

        try:
            shutil.rmtree(manager_dir)
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as e:
            self.logger.debug(
                "Failed to cleanup Windsurf manager dir %s: %s",
                manager_dir,
                e,
            )

    def _get_language_server_binary(self) -> Optional[Path]:
        """Resolve the Windsurf local language server binary from the extension bundle."""
        if not self.extension_bundle_path:
            return None

        extension_root = self.extension_bundle_path.parent.parent
        bin_dir = extension_root / "bin"
        if not bin_dir.exists():
            return None

        candidates = []
        for path in sorted(bin_dir.glob("language_server*")):
            if not path.is_file():
                continue
            if path.name.endswith(".LICENSE") or path.name.endswith(".md"):
                continue
            candidates.append(path)

        if not candidates:
            return None

        executable_candidates = [
            path
            for path in candidates
            if path.suffix == ".exe" or path.stat().st_mode & 0o111
        ]
        preferred = executable_candidates or candidates
        return preferred[0]

    def _reserve_local_port(self) -> int:
        """Reserve an ephemeral localhost port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    def _run_node_json(
        self,
        node_binary: str,
        script: str,
        payload: Dict[str, Any],
        error_context: str,
    ) -> Dict[str, Any]:
        """Run a Node helper script and parse its JSON stdout."""
        try:
            result = subprocess.run(
                [node_binary, "-e", script],
                input=json.dumps(payload).encode("utf-8"),
                capture_output=True,
                check=False,
            )
        except Exception as e:
            self.logger.debug("%s failed to start: %s", error_context, e)
            return {}

        stdout = self._decode_subprocess_output(result.stdout)
        stderr = self._decode_subprocess_output(result.stderr)

        if result.returncode != 0:
            self.logger.debug("%s failed: %s", error_context, stderr.strip())
            return {}

        try:
            return json.loads(stdout)
        except Exception as e:
            stdout_preview = stdout[:200].replace("\n", "\\n")
            self.logger.debug(
                "%s returned invalid JSON: %s; stdout=%r",
                error_context,
                e,
                stdout_preview,
            )
            return {}

    def _decode_subprocess_output(self, value: Any) -> str:
        """Decode subprocess output without relying on platform default encodings."""
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

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
            self.logger.debug(
                "Failed to read Windsurf global storage database %s: %s",
                global_storage_db,
                e,
            )
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
        """Decode cached summary and active trajectory protobuf payloads."""
        node_binary = shutil.which("node")
        if not node_binary:
            self.logger.debug("Node.js is required to decode Windsurf cached trajectories")
            return {}

        if not self.extension_bundle_path or not self.extension_bundle_path.exists():
            self.logger.debug(
                "Windsurf extension bundle could not be resolved for cached trajectory decoding"
            )
            return {}

        request_payload = {
            "extension_bundle_path": str(self.extension_bundle_path),
            "workspaces": [
                {
                    "workspace_id": workspace_id,
                    "summary_b64": values.get("summary_b64", ""),
                    "active_b64": values.get("active_b64", ""),
                }
                for workspace_id, values in payloads.items()
            ],
        }

        return self._run_node_json(
            node_binary=node_binary,
            script=WINDSURF_CACHE_DECODE_SCRIPT,
            payload=request_payload,
            error_context="Windsurf cache decoder",
        )

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

    def _load_json_chats(
        self,
        workspace_map: Dict[str, Dict[str, str]],
        allowed_session_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Load directly readable Windsurf JSON chat files."""
        chats: List[Dict[str, Any]] = []
        for session_file in self._list_session_files():
            session_data = self._read_json_file(session_file)
            if not session_data:
                continue

            session_id = str(session_data.get("session_id") or session_data.get("id") or session_file.stem)
            if allowed_session_ids is not None and session_id not in allowed_session_ids:
                continue

            chat = self._create_chat(
                session_data=session_data,
                session_file=session_file,
                workspace_map=workspace_map,
            )
            if chat and chat.get("messages"):
                chats.append(chat)
        return chats

    def _create_chat_from_trajectory(
        self,
        record: Dict[str, Any],
        trajectory_response: Dict[str, Any],
        workspace_map: Dict[str, Dict[str, str]],
        storage_kind: str,
    ) -> Optional[Dict[str, Any]]:
        """Normalize a decoded historical trajectory into the export format."""
        active_trajectory = {
            "cascadeId": record["session_id"],
            "trajectory": trajectory_response.get("trajectory", {}),
            "status": trajectory_response.get("status"),
        }
        return self._create_chat_from_active_trajectory(
            workspace_id=record["workspace_id"],
            active_trajectory=active_trajectory,
            summary=record["summary"],
            workspace_map=workspace_map,
            storage_kind=storage_kind,
        )

    def _create_chat_from_active_trajectory(
        self,
        workspace_id: str,
        active_trajectory: Dict[str, Any],
        summary: Dict[str, Any],
        workspace_map: Dict[str, Dict[str, str]],
        storage_kind: str,
    ) -> Optional[Dict[str, Any]]:
        """Normalize a Windsurf trajectory into the export format."""
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

        source_files = [str(self.app_root / "User" / "globalStorage" / "state.vscdb")]
        if storage_kind == "windsurf_pb":
            source_files.append(str(self.storage_root / "cascade" / f"{session_id}.pb"))

        storage_path = source_files[-1]

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
                "source_files": source_files,
                "storage_kind": storage_kind,
                "storage_path": storage_path,
                "workspace_id": workspace_id or "unknown",
                "trajectory_type": active_trajectory.get("trajectory", {}).get("trajectoryType"),
                "created_at": self._to_unix_seconds(created_at),
                "last_updated": self._to_unix_seconds(updated_at),
            },
        }

    def _store_preferred_chat(
        self,
        chats_by_id: Dict[str, Dict[str, Any]],
        chat: Dict[str, Any],
    ) -> None:
        """Keep the best available chat per session ID."""
        session_id = str(chat.get("session_id") or "")
        if not session_id:
            return

        existing = chats_by_id.get(session_id)
        if existing is None:
            chats_by_id[session_id] = chat
            return

        priority = {
            "windsurf_pb": 3,
            "windsurf_cache_active_fallback": 2,
            "windsurf_json": 1,
        }
        existing_kind = str(existing.get("metadata", {}).get("storage_kind") or "")
        new_kind = str(chat.get("metadata", {}).get("storage_kind") or "")
        if priority.get(new_kind, 0) > priority.get(existing_kind, 0):
            chats_by_id[session_id] = chat
            return

        if len(chat.get("messages", [])) > len(existing.get("messages", [])):
            chats_by_id[session_id] = chat

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

    def _create_chat(
        self,
        session_data: Dict[str, Any],
        session_file: Path,
        workspace_map: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        """Create a normalized Windsurf chat object from a JSON export file."""
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
        """Normalize Windsurf JSON messages into the export format."""
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
        """Normalize trajectory steps into user and assistant messages."""
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
            self.logger.debug("Failed to read Windsurf JSON file %s: %s", path, e)
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

    def _default_windsurf_app_root(self) -> Path:
        """Return the platform default Windsurf app root."""
        resolved = get_windsurf_app_root()
        if resolved is not None:
            return resolved

        home = Path.home()
        return home / "Library" / "Application Support" / "Windsurf"

    def _default_windsurf_storage_root(self) -> Path:
        """Return the default Windsurf Codeium storage root."""
        resolved = get_windsurf_storage_root()
        if resolved is not None:
            return resolved
        return Path.home() / ".codeium" / "windsurf"
