"""
Reusable upload client for AnySpecs CLI.
"""

from __future__ import annotations

import json
import mimetypes
import requests
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class AnySpecsUploadClient:
    """AnySpecs file upload client"""

    DEFAULT_BASE_URL = "https://hub.anyspecs.cn/"
    OSS_DATE_FORMATS = {
        "yyyy-mm-dd": "%Y-%m-%d",
        "yyyy/mm/dd": "%Y/%m/%d",
    }

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: Optional[str] = None,
        use_http: bool = False,
    ):
        """Initialize client.

        Args:
            base_url: API base URL
            token: User access token (bearer-like string)
            use_http: Force using HTTP instead of HTTPS (diagnostics only)
        """
        self.base_url = base_url.rstrip("/")
        if use_http and self.base_url.startswith("https://"):
            self.base_url = self.base_url.replace("https://", "http://", 1)

        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AnySpecs-Upload-Client/1.0.0",
            "Accept": "application/json",
        })
        if self.token:
            self.session.headers.update({"Authorization": self.token})

    def set_token(self, token: str) -> None:
        self.token = token
        self.session.headers.update({"Authorization": token})

    def test_connection(self) -> bool:
        try:
            resp = self.session.get(f"{self.base_url}/api/status", timeout=10)
            if resp.status_code != 200:
                print(f"❌ Connection failed: HTTP {resp.status_code}")
                return False
            data = resp.json()
            if not data.get("success"):
                print(f"❌ Connection failed: {data.get('message', 'Unknown error')}")
                return False
            print(
                f"✅ Connection successful! System name: {data.get('data', {}).get('system_name', 'Unknown')}"
            )
            return True
        except requests.exceptions.SSLError as e:  # type: ignore[attr-defined]
            print(f"❌ SSL connection error: {e}")
            print("💡 This might be due to:")
            print("   - Network firewall blocking SSL connections")
            print("   - SSL certificate issues")
            print("   - Network instability")
            print("💡 Try using --http flag for testing: anyspecs upload --http --list")
            return False
        except requests.exceptions.Timeout as e:  # type: ignore[attr-defined]
            print(f"❌ Connection timeout: {e}")
            print("💡 The server might be slow or network is unstable")
            return False
        except requests.exceptions.ConnectionError as e:  # type: ignore[attr-defined]
            print(f"❌ Connection error: {e}")
            print("💡 Please check:")
            print("   - Network connection")
            print("   - Server URL is correct")
            print("   - Server is running")
            return False
        except requests.exceptions.RequestException as e:  # type: ignore[attr-defined]
            print(f"❌ Connection error: {e}")
            return False

    def validate_token(self) -> bool:
        if not self.token:
            print("❌ Access token not set")
            return False
        try:
            resp = self.session.get(f"{self.base_url}/api/file/")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    print("✅ Token validation successful!")
                    print("   Can access file management functionality")
                    return True
                print(f"❌ Token validation failed: {data.get('message', 'Unknown error')}")
                return False
            if resp.status_code == 401:
                print("❌ Token validation failed: Unauthorized access")
                return False
            print(f"❌ Token validation failed: HTTP {resp.status_code}")
            if resp.text:
                try:
                    err = resp.json()
                    print(f"   Error message: {err.get('message', 'Unknown error')}")
                except Exception:
                    print(f"   Response content: {resp.text}")
            return False
        except requests.exceptions.RequestException as e:  # type: ignore[attr-defined]
            print(f"❌ Token validation error: {e}")
            return False

    def upload_file(self, file_path: str, description: str = "") -> bool:
        if not self.token:
            print("❌ Access token not set")
            return False
        p = self._validate_local_file(file_path)
        if p is None:
            return False
        size = p.stat().st_size

        print(f"📁 Preparing to upload file: {p.name}")
        print(f"   Size: {self._format_file_size(size)}")
        print(f"   Description: {description or 'No description'}")

        try:
            data = {"description": description} if description else {}
            with p.open("rb") as file_handle:
                files = {"file": (p.name, file_handle, "application/octet-stream")}
                resp = self.session.post(
                    f"{self.base_url}/api/file/",
                    files=files,
                    data=data,
                )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    print("✅ File upload successful!")
                    return True
                print(f"❌ Upload failed: {result.get('message', 'Unknown error')}")
                return False
            print(f"❌ Upload failed: HTTP {resp.status_code}")
            if resp.text:
                try:
                    err = resp.json()
                    print(f"   Error message: {err.get('message', 'Unknown error')}")
                except Exception:
                    print(f"   Response content: {resp.text}")
            return False
        except requests.exceptions.RequestException as e:  # type: ignore[attr-defined]
            print(f"❌ Upload request error: {e}")
            return False
        except Exception as e:
            print(f"❌ Upload process error: {e}")
            return False

    def upload_exported_file(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
        description: str = "",
        username: str = "",
        oss_config: Optional[Dict[str, Any]] = None,
        date_format: str = "yyyy-mm-dd",
    ) -> bool:
        p = self._validate_local_file(file_path)
        if p is None:
            return False

        if not username:
            print("❌ OSS username is required")
            return False

        metadata = metadata or self.load_export_metadata(str(p))
        if not metadata:
            print(f"❌ Missing export metadata sidecar for: {p}")
            return False

        size = p.stat().st_size
        print(f"📁 Preparing to upload export file: {p.name}")
        print(f"   Size: {self._format_file_size(size)}")
        print(f"   Description: {description or 'No description'}")
        print(f"   OSS Username: {username}")

        try:
            bucket = self._create_oss_bucket(oss_config or {})
            normalized_metadata = self._normalize_oss_metadata_date(metadata, date_format)
            object_key = self._build_oss_object_key(p, normalized_metadata, username)
            headers = self._build_oss_headers(normalized_metadata, description, p)
            bucket.put_object_from_file(object_key, str(p), headers=headers)
            print("✅ Export file upload successful!")
            print(f"   OSS Path: {bucket.bucket_name}/{object_key}")
            return True
        except Exception as e:
            print(f"❌ Upload process error: {e}")
            return False

    def upload_directory_anyspecs(
        self,
        directory: str,
        description: str = "",
        on_success: Optional[Callable[[Path], None]] = None,
    ) -> Dict[str, int]:
        files = self.iter_files(directory)
        summary = {"success": 0, "failed": 0, "skipped": 0}
        for path in files:
            if self.upload_file(str(path), description):
                summary["success"] += 1
                if on_success:
                    on_success(path)
            else:
                summary["failed"] += 1
        return summary

    def upload_directory_oss(
        self,
        directory: str,
        description: str = "",
        username: str = "",
        oss_config: Optional[Dict[str, Any]] = None,
        date_format: str = "yyyy-mm-dd",
        on_success: Optional[Callable[[Path], None]] = None,
    ) -> Dict[str, int]:
        files = self.iter_files(directory)
        summary = {"success": 0, "failed": 0, "skipped": 0}

        for path in files:
            if path.name.endswith(".meta.json"):
                summary["skipped"] += 1
                continue

            metadata = self.load_export_metadata(str(path))
            if not metadata:
                summary["skipped"] += 1
                continue

            if self.upload_exported_file(
                str(path),
                metadata=metadata,
                description=description,
                username=username,
                oss_config=oss_config,
                date_format=date_format,
            ):
                summary["success"] += 1
                if on_success:
                    on_success(path)
            else:
                summary["failed"] += 1

        return summary

    def iter_files(self, directory: str) -> List[Path]:
        root = Path(directory)
        if not root.exists():
            print(f"❌ Directory does not exist: {root}")
            return []
        if not root.is_dir():
            print(f"❌ Not a valid directory: {root}")
            return []

        files = [path for path in root.rglob("*") if path.is_file()]
        return sorted(files, key=lambda path: str(path.relative_to(root)))

    @staticmethod
    def load_export_metadata(file_path: str) -> Optional[Dict[str, Any]]:
        path = Path(file_path)
        meta_path = AnySpecsUploadClient.get_export_metadata_path(path)
        if not meta_path.exists() or not meta_path.is_file():
            return None

        try:
            with meta_path.open("r", encoding="utf-8") as meta_file:
                data = json.load(meta_file)
        except Exception:
            return None

        if not isinstance(data, dict):
            return None
        return data

    @staticmethod
    def get_export_metadata_path(file_path: Path) -> Path:
        return file_path.parent / f"{file_path.name}.meta.json"

    @staticmethod
    def _build_oss_headers(
        metadata: Dict[str, Any],
        description: str,
        file_path: Path,
    ) -> Dict[str, str]:
        headers = {
            "x-oss-meta-source": str(metadata.get("source", "")),
            "x-oss-meta-session-id": str(metadata.get("session_id", "")),
            "x-oss-meta-format": str(metadata.get("format", "")),
            "x-oss-meta-chat-date": str(metadata.get("chat_date", "")),
            "x-oss-meta-dedupe-key": str(metadata.get("dedupe_key", "")),
        }
        if description:
            headers["x-oss-meta-description"] = description

        content_type, _ = mimetypes.guess_type(file_path.name)
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    @classmethod
    def _normalize_oss_metadata_date(
        cls,
        metadata: Dict[str, Any],
        date_format: str,
    ) -> Dict[str, Any]:
        normalized_metadata = dict(metadata)
        normalized_metadata["chat_date"] = cls._format_oss_chat_date(
            normalized_metadata.get("chat_date"),
            date_format,
        )
        return normalized_metadata

    @classmethod
    def _format_oss_chat_date(cls, raw_value: Any, date_format: str) -> str:
        date_obj = cls._parse_oss_chat_date(raw_value)
        if date_obj is None:
            date_obj = datetime.now(timezone.utc).date()
        return date_obj.strftime(cls.OSS_DATE_FORMATS.get(date_format, "%Y-%m-%d"))

    @staticmethod
    def _parse_oss_chat_date(raw_value: Any) -> Optional[date]:
        if not raw_value:
            return None

        if isinstance(raw_value, datetime):
            return raw_value.date()

        raw_text = str(raw_value).strip()
        if not raw_text:
            return None

        for pattern in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw_text, pattern).date()
            except ValueError:
                continue

        return None

    @staticmethod
    def _build_oss_object_key(
        file_path: Path,
        metadata: Dict[str, Any],
        username: str,
    ) -> str:
        chat_date = str(metadata.get("chat_date", "")).strip("/")
        if chat_date:
            date_part = chat_date
        else:
            date_part = AnySpecsUploadClient._format_oss_chat_date(
                None,
                "yyyy-mm-dd",
            )
        return f"{username}/{date_part}/{file_path.name}"

    @staticmethod
    def _create_oss_bucket(oss_config: Dict[str, Any]):
        try:
            import oss2
        except ImportError as exc:
            raise RuntimeError(
                "oss2 is not installed. Please install AnySpecs with OSS support."
            ) from exc

        bucket_name = str(oss_config.get("bucket") or "").strip()
        access_key_id = str(oss_config.get("access_key_id") or "").strip()
        access_key_secret = str(oss_config.get("access_key_secret") or "").strip()
        endpoint = AnySpecsUploadClient._normalize_oss_endpoint(
            str(oss_config.get("endpoint") or "").strip(),
            str(oss_config.get("region") or "").strip(),
        )

        missing = []
        if not bucket_name:
            missing.append("OSS_BUCKET")
        if not access_key_id:
            missing.append("OSS_ACCESS_KEY_ID")
        if not access_key_secret:
            missing.append("OSS_ACCESS_KEY_SECRET")
        if not endpoint:
            missing.append("OSS_ENDPOINT or OSS_REGION")
        if missing:
            raise RuntimeError(f"Missing OSS configuration: {', '.join(missing)}")

        auth = oss2.Auth(access_key_id, access_key_secret)
        return oss2.Bucket(auth, endpoint, bucket_name)

    @staticmethod
    def _normalize_oss_endpoint(endpoint: str, region: str) -> str:
        if endpoint:
            if endpoint.startswith("http://") or endpoint.startswith("https://"):
                return endpoint
            return f"https://{endpoint}"
        if region:
            return f"https://oss-{region}.aliyuncs.com"
        return ""

    @staticmethod
    def _validate_local_file(file_path: str) -> Optional[Path]:
        p = Path(file_path)
        if not p.exists():
            print(f"❌ File does not exist: {p}")
            return None
        if not p.is_file():
            print(f"❌ Not a valid file: {p}")
            return None
        if p.stat().st_size == 0:
            print(f"❌ File is empty: {p}")
            return None
        return p

    def list_files(self, page: int = 0, search: str = "") -> bool:
        if not self.token:
            print("❌ Access token not set")
            return False
        try:
            params = {"p": page}
            if search:
                params["keyword"] = search
            if search:
                resp = self.session.get(f"{self.base_url}/api/file/search", params=params)
            else:
                resp = self.session.get(f"{self.base_url}/api/file/", params=params)
            if resp.status_code != 200:
                print(f"❌ Failed to get file list: HTTP {resp.status_code}")
                return False
            result = resp.json()
            if not result.get("success"):
                print(f"❌ Failed to get file list: {result.get('message', 'Unknown error')}")
                return False
            files = result.get("data", [])
            if not files:
                print("📋 No files available")
                return True
            print(f"📋 File list (Page {page + 1}):")
            print("-" * 80)
            print(f"{'ID':<4} {'Filename':<30} {'Size':<10} {'Uploader':<15} {'Upload Time':<20}")
            print("-" * 80)
            for info in files:
                file_id = info.get("id", "N/A")
                filename_full = info.get("filename", "N/A")
                filename = (
                    filename_full[:28] + ".." if len(filename_full) > 30 else filename_full
                )
                uploader_full = info.get("uploader", "N/A")
                uploader = (
                    uploader_full[:13] + ".." if len(uploader_full) > 15 else uploader_full
                )
                upload_time = info.get("upload_time", "N/A")
                print(f"{file_id:<4} {filename:<30} {'N/A':<10} {uploader:<15} {upload_time:<20}")
            print("-" * 80)
            print(f"Total: {len(files)} files")
            return True
        except requests.exceptions.RequestException as e:  # type: ignore[attr-defined]
            print(f"❌ Error getting file list: {e}")
            return False

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        while size >= 1024 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        return f"{size:.1f} {size_names[i]}"
