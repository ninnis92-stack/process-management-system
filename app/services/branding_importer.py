from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
import os
import re

import requests
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename


THEME_SWATCHES = {
    "default": "#4f8cff",
    "sky": "#3ec1d3",
    "moss": "#7bc96f",
    "dawn": "#ff8a5b",
    "twilight": "#7a5cff",
}


class BrandingImportError(ValueError):
    """Raised when branding cannot be safely imported from a website."""


@dataclass
class ImportedBranding:
    brand_name: str | None
    company_url: str
    theme_preset: str | None
    logo_filename: str | None
    source_url: str


class _BrandingHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts: list[str] = []
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_map = {str(k).lower(): str(v) for k, v in attrs if k and v is not None}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").strip().lower()
            val = (attrs_map.get("content") or "").strip()
            if key and val:
                self.meta[key] = val
        elif tag == "link":
            self.links.append(attrs_map)
        elif tag == "img":
            self.images.append(attrs_map)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and data:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(part.strip() for part in self.title_parts if part and part.strip()).strip()


def _normalize_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrandingImportError("Enter a valid website URL starting with http:// or https://")
    clean = parsed._replace(fragment="")
    return clean.geturl()


def _title_to_brand_name(title: str | None) -> str | None:
    if not title:
        return None
    for sep in (" | ", " — ", " – ", " - "):
        if sep in title:
            first = title.split(sep, 1)[0].strip()
            if first:
                return first[:120]
    return title.strip()[:120] or None


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3 and re.fullmatch(r"[0-9a-fA-F]{3}", raw):
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        return None
    return tuple(int(raw[idx:idx + 2], 16) for idx in (0, 2, 4))


def _closest_theme_preset(color: str | None) -> str | None:
    target = _hex_to_rgb(color or "")
    if not target:
        return None
    best_name = None
    best_distance = None
    for name, swatch in THEME_SWATCHES.items():
        rgb = _hex_to_rgb(swatch)
        if not rgb:
            continue
        distance = sum((target[i] - rgb[i]) ** 2 for i in range(3))
        if best_distance is None or distance < best_distance:
            best_name = name
            best_distance = distance
    return best_name


def _candidate_logo_urls(parser: _BrandingHTMLParser, source_url: str) -> list[str]:
    candidates: list[str] = []

    for key in ("og:image", "twitter:image", "twitter:image:src"):
        value = parser.meta.get(key)
        if value:
            candidates.append(urljoin(source_url, value))

    for link in parser.links:
        rel = (link.get("rel") or "").lower()
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if any(token in rel for token in ("icon", "apple-touch-icon", "mask-icon")):
            candidates.append(urljoin(source_url, href))

    def _image_score(image: dict[str, str]) -> int:
        haystack = " ".join(
            [image.get("alt", ""), image.get("class", ""), image.get("id", ""), image.get("src", "")]
        ).lower()
        score = 0
        if "logo" in haystack:
            score += 5
        if "brand" in haystack:
            score += 3
        if "header" in haystack or "nav" in haystack:
            score += 1
        return score

    for image in sorted(parser.images, key=_image_score, reverse=True):
        src = (image.get("src") or "").strip()
        if src:
            candidates.append(urljoin(source_url, src))

    deduped: list[str] = []
    seen = set()
    for url in candidates:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _safe_logo_extension(content_type: str | None, source_url: str) -> str | None:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/x-icon": ".ico",
    }
    lowered = (content_type or "").split(";", 1)[0].strip().lower()
    if lowered in mapping:
        return mapping[lowered]
    path = urlparse(source_url).path or ""
    ext = os.path.splitext(path)[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico"}:
        return ".jpg" if ext == ".jpeg" else ext
    return None


def _is_safe_image_bytes(data: bytes, extension: str) -> bool:
    if extension == ".svg":
        return data.lstrip().startswith(b"<") and len(data) <= 1024 * 1024
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def _download_logo(candidate_urls: Iterable[str], *, static_folder: str) -> str | None:
    for candidate in candidate_urls:
        try:
            response = requests.get(candidate, timeout=8, headers={"User-Agent": "FreshProcess Branding Importer/1.0"})
            response.raise_for_status()
        except requests.RequestException:
            continue
        extension = _safe_logo_extension(response.headers.get("Content-Type"), candidate)
        if not extension:
            continue
        content = response.content or b""
        if not content or len(content) > 2 * 1024 * 1024:
            continue
        if not _is_safe_image_bytes(content, extension):
            continue
        rel_dir = Path("uploads") / "branding"
        abs_dir = Path(static_folder) / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)
        safe_base = secure_filename(Path(urlparse(candidate).path).stem or "imported_logo") or "imported_logo"
        filename = f"{safe_base[:40]}_imported{extension}"
        target = abs_dir / filename
        counter = 1
        while target.exists():
            filename = f"{safe_base[:40]}_imported_{counter}{extension}"
            target = abs_dir / filename
            counter += 1
        target.write_bytes(content)
        return str((rel_dir / filename).as_posix())
    return None


def import_branding_from_url(url: str, *, static_folder: str) -> ImportedBranding:
    source_url = _normalize_url(url)
    try:
        response = requests.get(source_url, timeout=8, headers={"User-Agent": "FreshProcess Branding Importer/1.0"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BrandingImportError("Unable to fetch the website for branding import") from exc

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "html" not in content_type and "xml" not in content_type and not response.text:
        raise BrandingImportError("The provided URL did not return an HTML page")

    parser = _BrandingHTMLParser()
    parser.feed(response.text)

    brand_name = (
        parser.meta.get("og:site_name")
        or parser.meta.get("application-name")
        or _title_to_brand_name(parser.title)
    )
    brand_name = (brand_name or "").strip()[:120] or None

    theme_preset = _closest_theme_preset(
        parser.meta.get("theme-color") or parser.meta.get("msapplication-tilecolor")
    )

    canonical = None
    for link in parser.links:
        rel = (link.get("rel") or "").lower()
        href = (link.get("href") or "").strip()
        if href and "canonical" in rel:
            canonical = urljoin(source_url, href)
            break

    logo_filename = _download_logo(_candidate_logo_urls(parser, source_url), static_folder=static_folder)
    return ImportedBranding(
        brand_name=brand_name,
        company_url=_normalize_url(canonical or source_url),
        theme_preset=theme_preset,
        logo_filename=logo_filename,
        source_url=source_url,
    )