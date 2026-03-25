"""
Path utilities and project name extraction.
"""

import os
import platform
import pathlib
import re
from typing import List, Optional, Tuple

from ..config.runtime import config


def get_project_name() -> str:
    """Get the current project name from the current working directory."""
    try:
        current_dir = pathlib.Path.cwd()
        project_name = current_dir.name
        
        # Skip common container directory names
        container_dirs = ['Documents', 'Projects', 'Code', 'workspace', 'repos', 'git', 'src', 'codebase']
        if project_name in container_dirs and current_dir.parent.exists():
            project_name = current_dir.parent.name
        
        return project_name
    except Exception:
        return "unknown"


def normalize_path(path: str) -> pathlib.Path:
    """Normalize and resolve a path."""
    return pathlib.Path(path).expanduser().resolve()


def get_home_directory() -> pathlib.Path:
    """Get the user's home directory."""
    return pathlib.Path.home()


def sanitize_filename_component(
    value: Optional[str],
    fallback: str = "unknown",
    max_length: Optional[int] = None,
) -> str:
    """Sanitize a filename component for cross-platform safety."""
    if value is None:
        cleaned = ""
    else:
        cleaned = str(value).strip()

    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip(" ._")

    if not cleaned:
        cleaned = fallback

    if max_length is not None:
        cleaned = cleaned[:max_length].rstrip(" ._") or fallback

    return cleaned


def get_cursor_root() -> pathlib.Path:
    """Get the Cursor application data root directory."""
    home = pathlib.Path.home()
    system = platform.system()
    
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Cursor"
    elif system == "Windows":
        return home / "AppData" / "Roaming" / "Cursor"
    elif system == "Linux":
        return home / ".config" / "Cursor"
    else:
        raise RuntimeError(f"Unsupported OS: {system}")


def get_windsurf_app_root() -> Optional[pathlib.Path]:
    """Get the Windsurf application data root directory."""
    resolved_path, _ = resolve_windsurf_app_root()
    return resolved_path


def get_windsurf_storage_root() -> Optional[pathlib.Path]:
    """Get the Windsurf local Codeium storage root directory."""
    resolved_path, _ = resolve_windsurf_storage_root()
    return resolved_path


def get_windsurf_extension_bundle_path() -> Optional[pathlib.Path]:
    """Get the Windsurf extension bundle path when it exists."""
    resolved_path, _ = resolve_windsurf_extension_bundle_path()
    return resolved_path


def resolve_windsurf_app_root() -> Tuple[Optional[pathlib.Path], str]:
    """Resolve the Windsurf application root with env/config/platform precedence."""
    return _resolve_existing_path(
        env_var="ANYSPECS_WINDSURF_APP_ROOT",
        config_key="sources.windsurf.app_root",
        auto_candidates=_get_windsurf_app_root_candidates(),
        default_source="platform_default",
    )


def resolve_windsurf_storage_root() -> Tuple[Optional[pathlib.Path], str]:
    """Resolve the Windsurf Codeium storage root with env/config/platform precedence."""
    return _resolve_existing_path(
        env_var="ANYSPECS_WINDSURF_STORAGE_ROOT",
        config_key="sources.windsurf.storage_root",
        auto_candidates=[pathlib.Path.home() / ".codeium" / "windsurf"],
        default_source="default_storage_root",
    )


def resolve_windsurf_extension_bundle_path() -> Tuple[Optional[pathlib.Path], str]:
    """Resolve the Windsurf extension bundle with env/config/platform precedence."""
    return _resolve_existing_path(
        env_var="ANYSPECS_WINDSURF_EXTENSION_BUNDLE",
        config_key="sources.windsurf.extension_bundle_path",
        auto_candidates=_get_windsurf_extension_bundle_candidates(),
        default_source="platform_auto",
    )


def _resolve_existing_path(
    env_var: str,
    config_key: str,
    auto_candidates: List[pathlib.Path],
    default_source: str,
) -> Tuple[Optional[pathlib.Path], str]:
    """Resolve the first existing path from env, config, or platform defaults."""
    env_value = _existing_path_from_text(os.getenv(env_var))
    if env_value is not None:
        return env_value, f"env:{env_var}"

    config_value = _existing_path_from_text(config.get(config_key))
    if config_value is not None:
        return config_value, f"config:{config_key}"

    for candidate in auto_candidates:
        existing_candidate = _existing_path(candidate)
        if existing_candidate is not None:
            return existing_candidate, default_source

    return None, "unresolved"


def _existing_path_from_text(value: Optional[str]) -> Optional[pathlib.Path]:
    """Expand and return a path only when it already exists."""
    if not value:
        return None
    return _existing_path(pathlib.Path(str(value)).expanduser())


def _existing_path(path: pathlib.Path) -> Optional[pathlib.Path]:
    """Return the resolved path when it exists on disk."""
    try:
        expanded = path.expanduser()
        if not expanded.exists():
            return None
        return expanded.resolve()
    except Exception:
        return None


def _get_windsurf_app_root_candidates() -> List[pathlib.Path]:
    """Return platform-specific Windsurf app root candidates."""
    home = pathlib.Path.home()
    system = platform.system()

    if system == "Darwin":
        return [home / "Library" / "Application Support" / "Windsurf"]
    if system == "Windows":
        return [home / "AppData" / "Roaming" / "Windsurf"]
    if system == "Linux":
        return [home / ".config" / "Windsurf"]
    return []


def _get_windsurf_extension_bundle_candidates() -> List[pathlib.Path]:
    """Return platform-specific Windsurf extension bundle candidates."""
    home = pathlib.Path.home()
    system = platform.system()

    if system == "Darwin":
        return [
            pathlib.Path("/Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/dist/extension.js"),
            home / "Applications" / "Windsurf.app" / "Contents" / "Resources" / "app" / "extensions" / "windsurf" / "dist" / "extension.js",
        ]

    if system == "Windows":
        candidates: List[pathlib.Path] = []
        local_app_data = os.getenv("LOCALAPPDATA")
        program_files = os.getenv("ProgramFiles")
        if local_app_data:
            candidates.append(
                pathlib.Path(local_app_data)
                / "Programs"
                / "Windsurf"
                / "resources"
                / "app"
                / "extensions"
                / "windsurf"
                / "dist"
                / "extension.js"
            )
        if program_files:
            candidates.append(
                pathlib.Path(program_files)
                / "Windsurf"
                / "resources"
                / "app"
                / "extensions"
                / "windsurf"
                / "dist"
                / "extension.js"
            )
        return candidates

    if system == "Linux":
        return [
            pathlib.Path("/opt/Windsurf/resources/app/extensions/windsurf/dist/extension.js"),
            pathlib.Path("/usr/share/windsurf/resources/app/extensions/windsurf/dist/extension.js"),
            home / ".local" / "share" / "Windsurf" / "resources" / "app" / "extensions" / "windsurf" / "dist" / "extension.js",
        ]

    return []


def get_claude_history_path(project_path: Optional[str] = None) -> pathlib.Path:
    """Get the Claude Code history path for a project."""
    if project_path is None:
        project_path = os.getcwd()
    
    encoded_path = project_path.replace('/', '-')
    history_base = get_claude_projects_root()
    return history_base / encoded_path


def get_claude_projects_root() -> pathlib.Path:
    """Get the Claude Code projects root directory."""
    return pathlib.Path.home() / '.claude' / 'projects'


def extract_project_name_from_path(root_path: str, debug: bool = False) -> str:
    """Extract a project name from a path, skipping user directories."""
    if not root_path or root_path == '/':
        return "Root"

    normalized_path = re.sub(r"[\\/]+", "/", str(root_path).strip())
    normalized_path = re.sub(r"^[A-Za-z]:", "", normalized_path)
    path_parts = [p for p in normalized_path.split('/') if p and p != '.']
    
    # Skip common user directory patterns
    project_name = None
    home_dir_patterns = ['Users', 'home']
    
    # Get current username for comparison
    current_username = os.path.basename(os.path.expanduser('~'))
    
    # Find user directory in path
    username_index = -1
    for i, part in enumerate(path_parts):
        if part in home_dir_patterns:
            username_index = i + 1
            break
    
    # If this is just /Users/username with no deeper path, don't use username as project
    if username_index >= 0 and len(path_parts) <= username_index + 1:
        return "Home Directory"
    
    if username_index >= 0 and username_index + 1 < len(path_parts):
        # First try specific project directories we know about by name
        known_projects = ['genaisf', 'cursor-view', 'cursor', 'cursor-apps', 'universal-github', 'inquiry']
        
        # Look at the most specific/deepest part of the path first
        for i in range(len(path_parts)-1, username_index, -1):
            if path_parts[i] in known_projects:
                project_name = path_parts[i]
                break
        
        # If no known project found, use the last part of the path as it's likely the project directory
        if not project_name and len(path_parts) > username_index + 1:
            # Check if we have a structure like /Users/username/Documents/codebase/project_name
            if 'Documents' in path_parts and 'codebase' in path_parts:
                doc_index = path_parts.index('Documents')
                codebase_index = path_parts.index('codebase')
                
                # If there's a path component after 'codebase', use that as the project name
                if codebase_index + 1 < len(path_parts):
                    project_name = path_parts[codebase_index + 1]
            
            # If no specific structure found, use the last component of the path
            if not project_name:
                project_name = path_parts[-1]
        
        # Skip username as project name
        if project_name == current_username:
            project_name = 'Home Directory'
        
        # Skip common project container directories
        project_containers = [
            'Documents', 'Desktop', 'Downloads', 'Projects', 'Code', 'workspace',
            'repos', 'git', 'src', 'codebase'
        ]
        if project_name in project_containers:
            # Don't use container directories as project names
            # Try to use the next component if available
            container_index = path_parts.index(project_name)
            if container_index + 1 < len(path_parts):
                project_name = path_parts[container_index + 1]
        
        # If we still don't have a project name, use the first non-system directory after username
        if not project_name and username_index + 1 < len(path_parts):
            system_dirs = ['Library', 'Applications', 'System', 'var', 'opt', 'tmp']
            for i in range(username_index + 1, len(path_parts)):
                if path_parts[i] not in system_dirs and path_parts[i] not in project_containers:
                    project_name = path_parts[i]
                    break
    else:
        # If not in a user directory, use the basename
        project_name = path_parts[-1] if path_parts else "Root"
    
    # Final check: don't return username as project name
    if project_name == current_username:
        project_name = "Home Directory"
    
    return project_name if project_name else "Unknown Project" 
