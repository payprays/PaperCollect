"""WebDAV sync client for uploading/downloading paper JSON files."""

import os
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import requests
from requests.auth import HTTPBasicAuth


class WebDAVClient:
    """Simple WebDAV client using requests."""

    def __init__(self, url: str, username: str = "", password: str = "", verify_ssl: bool = True) -> None:
        self.url = url.rstrip("/") + "/"
        self.auth = HTTPBasicAuth(username, password) if username else None
        self.session = requests.Session()
        if self.auth:
            self.session.auth = self.auth
        self.session.verify = verify_ssl

    def ensure_directory(self, remote_path: str = "/") -> None:
        """MKCOL to create remote directory (recursive)."""
        if not remote_path or remote_path == "/":
            return
        parts = remote_path.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}"
            target = self.url + current.strip("/") + "/"
            try:
                resp = self.session.request("MKCOL", target, timeout=30)
                # 201 = created, 405 = already exists, 301/409 = parent missing (continue)
                if resp.status_code not in (201, 405, 301, 409):
                    resp.raise_for_status()
            except requests.RequestException:
                pass

    def list_files(self, remote_path: str = "/", timeout: int = 120) -> list[dict[str, Any]]:
        """PROPFIND to list remote files. Returns list of dicts with name, size, modified."""
        target = self.url + remote_path.strip("/") + "/"
        headers = {"Depth": "1", "Content-Type": "application/xml"}
        body = '<?xml version="1.0" encoding="utf-8"?><D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>'
        try:
            resp = self.session.request(
                "PROPFIND", target, headers=headers, data=body, timeout=timeout
            )
        except requests.RequestException:
            return []
        if resp.status_code != 207:
            return []
        return self._parse_propfind(resp.text, remote_path)

    def _parse_propfind(self, xml_text: str, remote_path: str) -> list[dict[str, Any]]:
        """Parse PROPFIND multistatus XML response."""
        files: list[dict[str, Any]] = []
        ns = {"d": "DAV:"}
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        for response in root.findall(".//d:response", ns):
            href_el = response.find("d:href", ns)
            if href_el is None or not href_el.text:
                continue
            href = unquote(href_el.text)
            # Skip directories (entries ending with /)
            if href.endswith("/"):
                continue
            name = href.rstrip("/").rsplit("/", 1)[-1]
            if not name:
                continue
            size_el = response.find(".//d:getcontentlength", ns)
            modified_el = response.find(".//d:getlastmodified", ns)
            files.append({
                "name": name,
                "size": int(size_el.text) if size_el is not None and size_el.text else 0,
                "modified": modified_el.text if modified_el is not None and modified_el.text else "",
            })
        return files

    def upload_file(self, local_path: str, remote_path: str) -> None:
        """PUT upload a single file."""
        with open(local_path, "rb") as f:
            data = f.read()
        target = self.url + remote_path.strip("/")
        resp = self.session.put(target, data=data, timeout=60)
        resp.raise_for_status()

    def download_file(self, remote_path: str, local_path: str) -> None:
        """GET download a single file."""
        target = self.url + remote_path.strip("/")
        resp = self.session.get(target, timeout=60, stream=True)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        temp_path = local_path + ".tmp"
        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        os.replace(temp_path, local_path)

    def file_exists(self, remote_path: str) -> bool:
        """HEAD check if remote file exists."""
        target = self.url + remote_path.strip("/")
        try:
            resp = self.session.head(target, timeout=15)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def delete_file(self, remote_path: str) -> None:
        """DELETE a remote file."""
        target = self.url + remote_path.strip("/")
        resp = self.session.delete(target, timeout=30)
        resp.raise_for_status()


def load_webdav_config(config: dict[str, Any]) -> dict[str, str] | None:
    """Load WebDAV config from config.yaml and environment variables.

    Environment variables take priority over config.yaml values.
    Returns None if no URL is configured.
    """
    webdav = config.get("webdav") or {}
    url = os.environ.get("WEBDAV_URL") or webdav.get("url", "")
    username = os.environ.get("WEBDAV_USERNAME") or webdav.get("username", "")
    password = os.environ.get("WEBDAV_PASSWORD") or webdav.get("password", "")
    remote_path = webdav.get("remote_path", "/")
    verify_ssl_str = os.environ.get("WEBDAV_VERIFY_SSL") or str(webdav.get("verify_ssl", "true"))
    verify_ssl = verify_ssl_str.lower() not in ("false", "0", "no")
    if not url:
        return None
    return {
        "url": url,
        "username": username,
        "password": password,
        "remote_path": remote_path or "/",
        "verify_ssl": verify_ssl,
    }


def _local_json_files(output_dir: str) -> dict[str, str]:
    """Map basename -> full path for *_*.json files in output_dir."""
    result: dict[str, str] = {}
    if not os.path.isdir(output_dir):
        return result
    for filename in os.listdir(output_dir):
        if not filename.endswith(".json"):
            continue
        # Match pattern: something_YEAR.json
        stem = filename.removesuffix(".json")
        _, _, year_part = stem.rpartition("_")
        if year_part.isdigit() and len(year_part) == 4:
            result[filename] = os.path.join(output_dir, filename)
    return result


def _remote_json_files(client: WebDAVClient, remote_path: str, timeout: int = 120) -> dict[str, dict[str, Any]]:
    """Map remote filename -> file info for JSON files."""
    result: dict[str, dict[str, Any]] = {}
    for entry in client.list_files(remote_path, timeout=timeout):
        name = entry.get("name", "")
        if name.endswith(".json"):
            result[name] = entry
    return result


def sync_upload(
    client: WebDAVClient,
    output_dir: str,
    remote_path: str = "/",
) -> dict[str, Any]:
    """Upload all *_*.json files from output_dir to WebDAV.

    Returns {"uploaded": [...], "skipped": [...], "errors": [...]}.
    """
    client.ensure_directory(remote_path)
    local_files = _local_json_files(output_dir)
    try:
        remote_files = _remote_json_files(client, remote_path)
    except Exception:
        remote_files = {}

    uploaded: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    for filename, local_path in local_files.items():
        local_size = os.path.getsize(local_path)
        remote_info = remote_files.get(filename)
        if remote_info and remote_info.get("size") == local_size:
            skipped.append(filename)
            continue
        remote_full = remote_path.rstrip("/") + "/" + filename
        try:
            client.upload_file(local_path, remote_full)
            uploaded.append(filename)
        except Exception as exc:
            errors.append({"file": filename, "error": str(exc)})

    return {"uploaded": uploaded, "skipped": skipped, "errors": errors}


def sync_download(
    client: WebDAVClient,
    output_dir: str,
    remote_path: str = "/",
) -> dict[str, Any]:
    """Download all JSON files from WebDAV to output_dir.

    Returns {"downloaded": [...], "skipped": [...], "errors": [...]}.
    """
    os.makedirs(output_dir, exist_ok=True)
    try:
        remote_files = _remote_json_files(client, remote_path)
    except Exception:
        remote_files = {}
    local_files = _local_json_files(output_dir)

    downloaded: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    for filename, remote_info in remote_files.items():
        local_path = os.path.join(output_dir, filename)
        local_exists = os.path.exists(local_path)
        if local_exists:
            local_size = os.path.getsize(local_path)
            if local_size == remote_info.get("size", 0):
                skipped.append(filename)
                continue
        remote_full = remote_path.rstrip("/") + "/" + filename
        try:
            client.download_file(remote_full, local_path)
            downloaded.append(filename)
        except Exception as exc:
            errors.append({"file": filename, "error": str(exc)})

    return {"downloaded": downloaded, "skipped": skipped, "errors": errors}


def sync_status(
    client: WebDAVClient,
    output_dir: str,
    remote_path: str = "/",
    timeout: int = 120,
) -> dict[str, Any]:
    """Compare local and remote file differences.

    Returns {"local_only": [...], "remote_only": [...], "both": [...], "remote_files": [...]}.
    """
    local_files = _local_json_files(output_dir)
    try:
        remote_files = _remote_json_files(client, remote_path, timeout=timeout)
    except Exception:
        remote_files = {}

    local_names = set(local_files.keys())
    remote_names = set(remote_files.keys())

    return {
        "local_only": sorted(local_names - remote_names),
        "remote_only": sorted(remote_names - local_names),
        "both": sorted(local_names & remote_names),
        "remote_files": [
            {"name": name, "size": info.get("size", 0), "modified": info.get("modified", "")}
            for name, info in sorted(remote_files.items())
        ],
    }
