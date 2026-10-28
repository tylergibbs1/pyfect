"""The content types of file extensions a static server knows."""

from __future__ import annotations

from collections.abc import Mapping

from pyfect.path import PathService

DEFAULT_MIME_TYPES: Mapping[str, str] = {
    "html": "text/html; charset=utf-8",
    "htm": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "mjs": "text/javascript; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "xml": "application/xml; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "yaml": "text/yaml; charset=utf-8",
    "yml": "text/yaml; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "svg": "image/svg+xml; charset=utf-8",
    "ico": "image/x-icon",
    "webp": "image/webp",
    "avif": "image/avif",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "eot": "application/vnd.ms-fontobject",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "gz": "application/gzip",
    "wasm": "application/wasm",
    "map": "application/json",
    "webmanifest": "application/manifest+json",
}


def resolve_mime_type(path: PathService, file_path: str, mime_types: Mapping[str, str]) -> str:
    extension = path.extname(file_path).lower()
    if len(extension) <= 1:
        return "application/octet-stream"
    return mime_types.get(extension[1:], "application/octet-stream")
