import asyncio
import datetime
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set
from urllib.parse import unquote, urljoin, urlparse

import aiofiles
import aiohttp
from bs4 import BeautifulSoup
import json
from pydantic import BaseModel

from logger import global_logger
from resource_governor import ResourceGovernor, ResourceOverloaded


class DownloadItem(BaseModel):
    id: str
    url: str
    name: str
    path: str
    total: int
    received: int
    state: str  # pending, downloading, completed, error, cancelled
    error: Optional[str] = None
    startTime: float
    contentType: Optional[str] = ""

    # Frontend reads `type`, so keep it aligned with contentType.
    type: Optional[str] = ""

    # Internal crawl depth (used for link discovery limits on HTML jobs).
    htmlDepth: int = 0


@dataclass(frozen=True)
class DownloadJob:
    id: str
    url: str
    content_type: str
    kind: str  # "asset" | "html"
    html_depth: int = 0


class DownloadManager:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or "c:/2em/nodejs/web-downloader/python-version/downloads"
        os.makedirs(self.base_dir, exist_ok=True)

        self.downloads: Dict[str, DownloadItem] = {}

        # Prevent duplicates and allow safe retries.
        self._processed_urls: Set[str] = set()  # only after successful write
        self._queued_url_to_id: Dict[str, str] = {}  # includes pending/downloading (for dedupe)

        self.browser_manager: Any = None
        self.ws_callback: Any = None

        self.resource_governor = ResourceGovernor()

        # Queue + worker pools (bounded concurrency to prevent freezes).
        self._asset_queue: Any = None
        self._html_queue: Any = None
        self._workers_started = False

        # Soft limits for crawl expansion to keep CPU bounded.
        self.max_html_pages_per_session = 100
        self.max_html_depth = 4
        self.max_discovered_links_per_html = 800
        self.max_discovered_links_per_css = 300
        self.max_total_jobs = 3000

        self._enqueued_count = 0
        self._html_processed_count = 0
        self._html_enqueued_count = 0

        # Used to protect state maps during concurrent workers.
        self._state_lock: Any = None

        # Shared aiohttp session (connection limits reduce memory spikes).
        self._http_session: Optional[aiohttp.ClientSession] = None

        # Worker counts are conservative. Governor further reduces work by blocking resources and pausing starts.
        self.asset_workers = 4
        self.html_workers = 1

        self._asset_workers_tasks: list[asyncio.Task] = []
        self._html_workers_tasks: list[asyncio.Task] = []

        # Extra extracted JSON (apollo/next/etc.) size safety.
        # If content is too big, we write a truncated wrapper JSON instead.
        self.max_extracted_json_bytes_per_file = 8 * 1024 * 1024  # 8MB

    async def start_workers(self) -> None:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
            
        async with self._state_lock:
            if self._workers_started:
                return
            self._workers_started = True

            if self._asset_queue is None:
                self._asset_queue = asyncio.Queue()
            if self._html_queue is None:
                self._html_queue = asyncio.Queue()

            timeout = aiohttp.ClientTimeout(total=90)
            connector = aiohttp.TCPConnector(limit=16, limit_per_host=4, ttl_dns_cache=300)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/"
            }
            self._http_session = aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers)

            for i in range(self.asset_workers):
                self._asset_workers_tasks.append(asyncio.create_task(self._asset_worker(i)))
            for i in range(self.html_workers):
                self._html_workers_tasks.append(asyncio.create_task(self._html_worker(i)))

            global_logger.info(
                f"[*] Download workers started (asset={self.asset_workers}, html={self.html_workers})"
            )

    def sanitize_filename(self, name: str) -> str:
        chars = '<>:"/\\|?*()'
        for char in chars:
            name = name.replace(char, "_")
        name = name.strip()
        if len(name) > 100:
            ext = os.path.splitext(name)[1]
            name = name[:90] + "_trunc" + ext
        return name

    def get_target_root(self, url: str) -> str:
        d = datetime.datetime.now()
        date_str = d.strftime("%d_%m_%Y")
        parsed = urlparse(url)
        hostname = self.sanitize_filename(
            parsed.hostname.replace("www.", "") if parsed.hostname else "misc"
        )
        return os.path.join(self.base_dir, f"{hostname}_{date_str}")

    def get_mirror_path(self, target_root: str, url: str, content_type: str = "") -> str:
        # Safety: strip potential wrappers.
        url = url.strip().strip('"').strip("'")
        if url.lower().startswith("url("):
            url = url[4:].rstrip(")")
        url = url.strip().strip('"').strip("'")

        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1].lower()
        ct = (content_type or "").lower()

        category = ""
        if any(x in ct for x in ["image/", "image"]) or ext in [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".svg",
            ".ico",
            ".bmp",
            ".tiff",
            ".tif",
            ".avif",
            ".heic",
            ".heif",
        ]:
            category = "images"
        elif any(
            x in ct
            for x in [
                "video/",
                "video",
                "application/vnd.apple.mpegurl",
                "application/x-mpegurl",
                "application/dash+xml",
                "application/vnd.ms-sstr+xml",
            ]
        ) or ext in [
            ".mp4",
            ".webm",
            ".m4v",
            ".m3u8",
            ".m3u",
            ".ts",
            ".m2ts",
            ".mpd",
            ".m4s",
            ".ism",
            ".isml",
            ".ismv",
            ".mov",
            ".avi",
            ".mkv",
            ".flv",
            ".f4v",
            ".wmv",
            ".3gp",
        ]:
            category = "videos"
        elif any(
            x in ct
            for x in [
                "audio/",
                "audio",
                "application/ogg",
                "application/vnd.apple.mpegurl",
                "application/x-mpegurl",
            ]
        ) or ext in [
            ".mp3",
            ".wav",
            ".ogg",
            ".oga",
            ".opus",
            ".aac",
            ".m4a",
            ".flac",
            ".aiff",
            ".wma",
            ".amr",
        ]:
            category = "audio"
        elif "javascript" in ct or ext == ".js":
            category = "js"
        elif "css" in ct or ext == ".css":
            category = "css"

        filename = os.path.basename(path)
        default_ext = self._default_extension_for_content_type(ct)
        if not filename or path.endswith("/"):
            filename = f"index{default_ext}"
        filename = self.sanitize_filename(filename)
        filename_root, filename_ext = os.path.splitext(filename)
        ext_is_fake_version = bool(filename_ext) and filename_ext[1:].isdigit()
        if ext_is_fake_version and default_ext:
            filename = f"{filename}{default_ext}"
        elif not filename_ext:
            if default_ext:
                filename += default_ext
            elif category == "":
                filename += ".html"

        if category:
            full_path = os.path.join(target_root, category, filename)
        else:
            rel_dir = os.path.dirname(path.lstrip("/"))
            full_path = os.path.join(target_root, rel_dir, filename)

        full_path = os.path.normpath(full_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        return full_path

    def _default_extension_for_content_type(self, content_type: str) -> str:
        ct = (content_type or "").lower()
        def subtype_ext(prefix: str) -> str:
            subtype = ct.split(prefix, 1)[1].split(";")[0].strip()
            subtype = subtype.replace("+xml", "").replace("x-", "")
            subtype = subtype.split(".")[-1]
            return f".{subtype}" if subtype else ""

        if "text/html" in ct:
            return ".html"
        if "javascript" in ct:
            return ".js"
        if "text/css" in ct:
            return ".css"
        if "application/json" in ct or ct.endswith("+json"):
            return ".json"
        if "image/svg" in ct:
            return ".svg"
        if "image/" in ct:
            return subtype_ext("image/")
        if "font/woff2" in ct:
            return ".woff2"
        if "font/woff" in ct:
            return ".woff"
        if "font/ttf" in ct:
            return ".ttf"
        if "font/otf" in ct:
            return ".otf"
        if "video/" in ct:
            return subtype_ext("video/")
        if "audio/" in ct:
            return subtype_ext("audio/")
        if "application/vnd.apple.mpegurl" in ct or "application/x-mpegurl" in ct:
            return ".m3u8"
        if "application/dash+xml" in ct:
            return ".mpd"
        return ""

    def _is_html_content_type(self, content_type: str) -> bool:
        ct = (content_type or "").lower()
        return "text/html" in ct or "application/xhtml+xml" in ct

    def get_local_rel_path(self, link_url: str, current_page_url: str, current_page_path: str) -> Optional[str]:
        if not link_url or link_url.startswith(("#", "data:", "javascript:", "mailto:", "tel:")):
            return None

        link_url = link_url.strip().strip('"').strip("'").strip()
        if link_url.lower().startswith("url("):
            link_url = link_url[4:].rstrip(")").strip().strip('"').strip("'")

        absolute_url = urljoin(current_page_url, link_url)
        parsed_abs = urlparse(absolute_url)
        parsed_base = urlparse(current_page_url)

        target_root = self.get_target_root(current_page_url)
        if parsed_abs.hostname != parsed_base.hostname and parsed_abs.hostname:
            ext_root = os.path.join(target_root, "external", parsed_abs.hostname)
            target_file = self.get_mirror_path(ext_root, absolute_url)
        else:
            target_file = self.get_mirror_path(target_root, absolute_url)

        rel_path = os.path.relpath(target_file, os.path.dirname(current_page_path))
        return rel_path.replace("\\", "/")

    def _is_html_url(self, url: str, content_type: str) -> bool:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1].lower()
        ct = (content_type or "").lower()
        full = url.lower()

        cdn_keywords = [".fbcdn.", "static.", "scontent.", "cdn.", "images.", "assets."]
        is_cdn = any(k in (parsed.hostname or "").lower() for k in cdn_keywords)

        # Explicit non-HTML hints for extension-less endpoints.
        non_html_markers = [
            "/css", "/css2", "/styles", "stylesheet",
            "/js", "gtag/js", "rsrc.php", ".js?", ".css?",
            "font", "woff", "woff2", "ttf", "otf", "eot",
            "collect?", "/g/collect", "/analytics",
            "m3u8", "mpd", ".ts?", "bytestart=", "byteend=",
            "image", "video", "audio",
        ]
        if not ext and any(m in full for m in non_html_markers):
            return False

        if any(x in ct for x in ["text/css", "javascript", "font/", "image/", "video/", "audio/", "application/json"]):
            return False

        is_html = (
            not ext
            or ext in [".html", ".htm", ".php", ".asp", ".aspx", ".jsp"]
            or "text/html" in ct
        )
        return is_html and not is_cdn

    def _should_skip_existing(self, url: str, file_path: str) -> bool:
        if url in self._processed_urls:
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return True
        return False

    def _guess_type_from_url(self, url: str, content_type: str = "") -> str:
        ct = (content_type or "").strip()
        if ct:
            return ct
        path = urlparse(url).path.lower()
        if any(
            path.endswith(x)
            for x in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".tif", ".avif", ".heic", ".heif"]
        ):
            return "image/"
        if any(
            path.endswith(x)
            for x in [".mp4", ".webm", ".m4v", ".m3u8", ".m3u", ".ts", ".m2ts", ".mpd", ".m4s", ".mov", ".avi", ".mkv", ".flv", ".f4v", ".wmv", ".3gp"]
        ):
            return "video/"
        if any(path.endswith(x) for x in [".mp3", ".wav", ".ogg", ".oga", ".opus", ".aac", ".m4a", ".flac", ".aiff", ".wma", ".amr"]):
            return "audio/"
        if path.endswith(".css"):
            return "text/css"
        if path.endswith(".js"):
            return "application/javascript"
        return "application/octet-stream"

    async def start_download(self, url: str, content_type: str = "") -> Optional[DownloadItem]:
        # Safety: ensure workers are running even if startup hooks were not fired.
        await self.start_workers()

        if not url or not isinstance(url, str):
            return None
        url = url.strip().strip('"').strip("'")

        parsed = urlparse(url)
        if not parsed.scheme:
            # Keep existing behavior: assume http(s) when UI gives relative-ish URLs.
            url = f"https://{url}"

        target_root = self.get_target_root(url)
        temp_path = self.get_mirror_path(target_root, url, content_type)

        async with self._state_lock:
            if self._should_skip_existing(url, temp_path):
                return None

            existing_id = self._queued_url_to_id.get(url)
            if existing_id and existing_id in self.downloads:
                existing = self.downloads[existing_id]
                if existing.state in {"pending", "downloading"}:
                    return existing

            # Respect global job cap to prevent runaway queues.
            if self._enqueued_count >= self.max_total_jobs:
                global_logger.warn(
                    f"[QueueLimit] Not enqueuing more jobs (limit={self.max_total_jobs}). url={url}"
                )
                return None

            kind = "html" if self._is_html_url(url, content_type) else "asset"
            item_id = str(uuid.uuid4())
            name = os.path.basename(temp_path) or "file"

            content_type_norm = content_type or ""
            item = DownloadItem(
                id=item_id,
                url=url,
                name=name,
                path=temp_path,
                total=0,
                received=0,
                state="pending",
                error=None,
                startTime=time.time(),
                contentType=content_type_norm,
                type=self._guess_type_from_url(url, content_type_norm),
                htmlDepth=0,
            )

            self.downloads[item_id] = item
            self._queued_url_to_id[url] = item_id

            self._enqueued_count += 1

            job = DownloadJob(
                id=item_id,
                url=url,
                content_type=content_type_norm,
                kind=kind,
                html_depth=0,
            )

            if kind == "html":
                self._html_enqueued_count += 1
                await self._html_queue.put(job)
            else:
                await self._asset_queue.put(job)

            global_logger.info(
                f"[*] Enqueued ({kind}) {url} -> {os.path.relpath(temp_path, self.base_dir)}"
            )

            # Tell the frontend right away, even if workers are paused by the governor.
            if self.ws_callback:
                await self.ws_callback({"type": "progress", "data": item.dict()})

            return item

    async def enqueue_html(self, url: str, depth: int) -> Optional[DownloadItem]:
        # Safety: ensure workers are running even if startup hooks were not fired.
        await self.start_workers()

        # Enqueue with a crawl depth (internal recursion guard).
        if depth > self.max_html_depth:
            return None

        async with self._state_lock:
            if self._html_enqueued_count >= self.max_html_pages_per_session:
                return None

        parsed = urlparse(url)
        if not parsed.scheme:
            url = f"https://{url}"

        target_root = self.get_target_root(url)
        temp_path = self.get_mirror_path(target_root, url, "text/html")

        async with self._state_lock:
            if self._should_skip_existing(url, temp_path):
                return None
            existing_id = self._queued_url_to_id.get(url)
            if existing_id and existing_id in self.downloads:
                existing = self.downloads[existing_id]
                if existing.state in {"pending", "downloading"}:
                    return existing

            if self._enqueued_count >= self.max_total_jobs:
                return None

            item_id = str(uuid.uuid4())
            name = os.path.basename(temp_path) or "index.html"
            item = DownloadItem(
                id=item_id,
                url=url,
                name=name,
                path=temp_path,
                total=0,
                received=0,
                state="pending",
                error=None,
                startTime=time.time(),
                contentType="text/html",
                type="text/html",
                htmlDepth=depth,
            )
            self.downloads[item_id] = item
            self._queued_url_to_id[url] = item_id
            self._enqueued_count += 1
            job = DownloadJob(
                id=item_id,
                url=url,
                content_type="text/html",
                kind="html",
                html_depth=depth,
            )
            self._html_enqueued_count += 1
            await self._html_queue.put(job)

            global_logger.info(
                f"[*] Enqueued (html depth={depth}) {url} -> {os.path.relpath(temp_path, self.base_dir)}"
            )

            if self.ws_callback:
                await self.ws_callback({"type": "progress", "data": item.dict()})

            return item

    async def save_content_to_item(self, item_id: str, url: str, content: str, content_type: str) -> None:
        """
        Called by BrowserManager after hydration.
        Writes content safely to disk and enqueues discovered links.
        """
        item = self.downloads.get(item_id)
        if not item:
            return

        target_root = self.get_target_root(url)
        file_path = self.get_mirror_path(target_root, url, content_type)
        item.path = file_path
        item.url = url

        item.contentType = content_type
        item.type = content_type

        part_path = file_path + ".part"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Instead of aborting immediately on a spike, wait for capacity.
        # This avoids losing HTML files due to short cpu_percent peaks.
        await self.resource_governor.wait_for_capacity()

        # Write to .part to avoid leaving corrupted files if we stop under load.
        async with aiofiles.open(part_path, mode="w", encoding="utf-8", errors="ignore") as f:
            await f.write(content)

        try:
            os.replace(part_path, file_path)
        except Exception:
            # Ensure temp file doesn't accumulate.
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except Exception:
                pass
            raise

        item.received = len(content.encode("utf-8", errors="ignore"))
        item.total = item.received
        item.state = "completed"
        item.error = None

        if self.ws_callback:
            await self.ws_callback({"type": "completed", "data": item.dict()})

        global_logger.info(f"[*] Saved hydrated HTML: {url} -> {file_path}")

        # Parse + rewrite links with queue limits.
        # Only mark the URL as processed if rewriting succeeds.
        await self._rewrite_links_and_enqueue(url=url, file_path=file_path, html=content, item_id=item_id)

        async with self._state_lock:
            self._processed_urls.add(url)

    async def save_extracted_page_state(self, url: str, extracted: dict) -> None:
        """
        Saves JSON that already exists in the page state (Apollo/Next/inline application/json),
        without intercepting network traffic.
        """
        if not url or not extracted or not isinstance(extracted, dict):
            return

        cpu, mem = self.resource_governor.get_usage()
        if cpu >= self.resource_governor.config.stop_cpu or mem >= self.resource_governor.config.stop_mem:
            return
        if cpu >= self.resource_governor.config.pause_cpu or mem >= self.resource_governor.config.pause_mem:
            await asyncio.sleep(0.25)

        target_root = self.get_target_root(url)
        data_dir = os.path.join(target_root, "data")
        os.makedirs(data_dir, exist_ok=True)

        async def _write_json_safely(path: str, obj: object) -> None:
            try:
                text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
                if len(text.encode("utf-8", errors="ignore")) > self.max_extracted_json_bytes_per_file:
                    wrapped = {
                        "__truncated__": True,
                        "__max_bytes__": self.max_extracted_json_bytes_per_file,
                        "preview": text[:4000],
                    }
                    text = json.dumps(wrapped, ensure_ascii=False, separators=(",", ":"), default=str)
                async with aiofiles.open(path, mode="w", encoding="utf-8", errors="ignore") as f:
                    await f.write(text)
            except Exception as e:
                global_logger.warn(f"[ExtractSave] Failed to write {os.path.basename(path)}: {e}")

        next_data = extracted.get("next_data")
        if next_data is not None:
            await _write_json_safely(os.path.join(data_dir, "next_data.json"), next_data)

        apollo_state = extracted.get("apollo_state")
        if apollo_state is not None:
            await _write_json_safely(os.path.join(data_dir, "apollo_state.json"), apollo_state)

        inline_items = extracted.get("inline_application_json")
        if isinstance(inline_items, list) and inline_items:
            for i, entry in enumerate(inline_items[:20]):
                if not isinstance(entry, dict):
                    continue
                data = entry.get("data")
                if data is None:
                    continue
                safe_id = self.sanitize_filename(str(entry.get("id") or f"script_{i}"))
                await _write_json_safely(os.path.join(data_dir, f"inline_{safe_id}.json"), data)

    async def save_hydrated_html(
        self,
        url: str,
        content: str,
        content_type: str = "text/html",
        force: bool = False,
    ) -> Optional[DownloadItem]:
        """
        Directly saves hydrated HTML (used when we already have a loaded browser page).
        This keeps the HTML+rewrite behavior consistent with the queued hydration path.
        """
        if not url:
            return None

        url = url.strip()
        target_root = self.get_target_root(url)
        file_path = self.get_mirror_path(target_root, url, content_type)

        async with self._state_lock:
            if not force and url in self._processed_urls:
                if os.path.exists(file_path) and os.path.getsize(file_path) > 100:
                    return None

            if self._html_enqueued_count >= self.max_html_pages_per_session:
                return None

            item_id = str(uuid.uuid4())
            item = DownloadItem(
                id=item_id,
                url=url,
                name=os.path.basename(file_path) or "index.html",
                path=file_path,
                total=0,
                received=0,
                state="pending",
                error=None,
                startTime=time.time(),
                contentType=content_type,
                type=content_type,
                htmlDepth=0,
            )

            self.downloads[item_id] = item
            self._queued_url_to_id[url] = item_id
            self._enqueued_count += 1
            self._html_enqueued_count += 1

            if self.ws_callback:
                await self.ws_callback({"type": "progress", "data": item.dict()})

        await self.save_content_to_item(
            item_id=item_id,
            url=url,
            content=content,
            content_type=content_type,
        )
        return self.downloads.get(item_id)

    async def _rewrite_links_and_enqueue(self, url: str, file_path: str, html: str, item_id: str) -> None:
        try:
            # Parsing can be CPU-heavy; wait until capacity is available.
            await self.resource_governor.wait_for_capacity()

            soup = BeautifulSoup(html, "lxml")

            base_tag = soup.find("base", href=True)
            page_base_url = urljoin(url, base_tag["href"]) if base_tag else url

            discovered = 0
            enqueue_lock = asyncio.Lock()

            internal_depth = self.downloads.get(item_id).htmlDepth if self.downloads.get(item_id) else 0

            asset_tags = [
                ("a", "href"),
                ("img", "src"),
                ("img", "data-src"),
                ("link", "href"),
                ("script", "src"),
                ("source", "src"),
                ("source", "data-src"),
                ("track", "src"),
                ("embed", "src"),
                ("use", "xlink:href"),
                ("object", "data"),
                ("iframe", "src"),
                ("video", "src"),
                ("video", "poster"),
                ("video", "data-poster"),
                ("audio", "src"),
                ("div", "data-bg"),
                ("a", "data-href"),
            ]

            for tag, attr in asset_tags:
                for el in soup.find_all(tag, **{attr: True}):
                    if discovered >= self.max_discovered_links_per_html:
                        break

                    link_url = el.get(attr)
                    new_rel = self.get_local_rel_path(link_url, page_base_url, file_path)
                    if not new_rel:
                        continue

                    el[attr] = new_rel

                    # Enqueue downloads for the linked resources.
                    abs_url = urljoin(page_base_url, link_url)

                    parsed_abs = urlparse(abs_url)
                    parsed_base = urlparse(url)

                    # Decide kind:
                    if tag == "a":
                        # Crawl only for same-domain and limited depth.
                        if parsed_abs.hostname == parsed_base.hostname and internal_depth < self.max_html_depth:
                            enq = await self.enqueue_html(abs_url, depth=internal_depth + 1)
                            if enq:
                                discovered += 1
                        else:
                            # Still save assets if they look like html; but avoid recursive explosion.
                            pass
                    else:
                        enq = await self.start_download(abs_url, content_type="")
                        if enq:
                            discovered += 1

                if discovered >= self.max_discovered_links_per_html:
                    break

            # Parse srcset attributes for images and sources
            for el in soup.find_all(lambda tag: tag.name in ["img", "source"] and tag.has_attr("srcset")):
                if discovered >= self.max_discovered_links_per_html:
                    break
                srcset_val = el["srcset"]
                if not isinstance(srcset_val, str):
                    continue
                new_parts = []
                for part in srcset_val.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    tokens = part.split(" ", 1)
                    link_url = tokens[0]
                    new_rel = self.get_local_rel_path(link_url, page_base_url, file_path)
                    if new_rel:
                        tokens[0] = new_rel
                        abs_url = urljoin(page_base_url, link_url)
                        enq = await self.start_download(abs_url, content_type="")
                        if enq:
                            discovered += 1
                    new_parts.append(" ".join(tokens))
                el["srcset"] = ", ".join(new_parts)

            # Rewrite inline <style> blocks and style attributes
            css_discovered_abs_urls: list[str] = []
            style_pattern = re.compile(
                r'url\((["\']?)([^)]+)\1\)|@import\s+(["\']?)([^;]+)\3',
                re.I,
            )

            def css_replace(match):
                raw_wrapper = match.group(0)
                inner_url = match.group(2) or match.group(4)
                if not inner_url:
                    return raw_wrapper
                try:
                    new_rel = self.get_local_rel_path(inner_url, page_base_url, file_path)
                    if new_rel:
                        # Collect CSS assets to enqueue after we've updated the HTML string.
                        abs_u = urljoin(page_base_url, inner_url)
                        if len(css_discovered_abs_urls) < self.max_discovered_links_per_css:
                            css_discovered_abs_urls.append(abs_u)
                        return raw_wrapper.replace(inner_url, new_rel)
                except Exception:
                    pass
                return raw_wrapper

            for el in soup.find_all(style=True):
                style_val = el.get("style", "")
                if style_val and ("url(" in style_val.lower() or "@import" in style_val.lower()):
                    el["style"] = style_pattern.sub(css_replace, style_val)

            for style_tag in soup.find_all("style"):
                css_content = style_tag.string or ""
                style_tag.string = style_pattern.sub(css_replace, css_content)

            # Enqueue CSS url() / @import assets after HTML rewrite to keep concurrency bounded.
            for abs_u in css_discovered_abs_urls[: self.max_discovered_links_per_css]:
                await self.start_download(abs_u, content_type="")

            # Persist rewritten HTML.
            async with aiofiles.open(file_path, mode="w", encoding="utf-8", errors="ignore") as f:
                await f.write(str(soup))
        except Exception as e:
            global_logger.warn(f"HTML rewrite failed for {os.path.basename(file_path)}: {e}")

    # (depth is stored on the DownloadItem now; no infer helper)

    async def _rewrite_css_file(self, item: DownloadItem) -> None:
        try:
            if not os.path.exists(item.path):
                return
            async with aiofiles.open(item.path, mode="r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()

            style_pattern = re.compile(
                r'url\((["\']?)([^)]+)\1\)|@import\s+(["\']?)([^;]+)\3',
                re.I,
            )

            discovered_abs_urls: list[str] = []

            matches = list(style_pattern.finditer(content))
            # Modify from the end so indices don't shift.
            new_content = content
            applied = 0
            for match in reversed(matches):
                if applied >= self.max_discovered_links_per_css:
                    break
                raw_wrapper = match.group(0)
                inner_url = match.group(2) or match.group(4)
                if not inner_url:
                    continue
                try:
                    new_rel = self.get_local_rel_path(inner_url, item.url, item.path)
                    if not new_rel:
                        continue

                    abs_u = urljoin(item.url, inner_url)
                    discovered_abs_urls.append(abs_u)
                    applied += 1

                    replaced = raw_wrapper.replace(inner_url, new_rel)
                    new_content = new_content[: match.start()] + replaced + new_content[match.end() :]
                except Exception:
                    continue

            # Enqueue discovered URLs sequentially (bounded) to avoid task explosions.
            for abs_u in discovered_abs_urls[: self.max_discovered_links_per_css]:
                await self.start_download(abs_u, content_type="")

            async with aiofiles.open(item.path, mode="w", encoding="utf-8", errors="ignore") as f:
                await f.write(new_content)
        except Exception as e:
            global_logger.warn(f"CSS rewrite failed for {os.path.basename(item.path)}: {e}")

    async def _asset_worker(self, worker_idx: int) -> None:
        if not self._http_session:
            return

        while True:
            job = await self._asset_queue.get()
            item = self.downloads.get(job.id)
            if not item:
                self._asset_queue.task_done()
                continue

            try:
                global_logger.info(f"[*] Asset worker {worker_idx} picked job: {item.url}")
                await self.resource_governor.wait_for_capacity()
                async with self._state_lock:
                    item.state = "downloading"
                    item.error = None
                    if self.ws_callback:
                        await self.ws_callback({"type": "progress", "data": item.dict()})

                global_logger.info(f"[*] Asset worker {worker_idx} downloading: {item.url}")

                # Stream download to disk.
                session = self._http_session
                assert session is not None

                async with session.get(job.url, timeout=60, allow_redirects=True) as resp:
                    resp.raise_for_status()
                    # Update final URL/content-type and recalc target path.
                    final_url = str(resp.url) if resp.url else item.url
                    content_type = resp.headers.get("Content-Type", item.contentType) or ""

                    if self._is_html_content_type(content_type):
                        body = await resp.text(errors="ignore")
                        item.url = final_url
                        item.contentType = content_type
                        item.type = content_type
                        await self.save_content_to_item(
                            item_id=item.id,
                            url=final_url,
                            content=body,
                            content_type=content_type,
                        )
                        continue

                    target_root = self.get_target_root(final_url)
                    final_path = self.get_mirror_path(target_root, final_url, content_type)
                    part_path = final_path + ".part"
                    os.makedirs(os.path.dirname(final_path), exist_ok=True)
                    try:
                        if os.path.exists(part_path):
                            os.remove(part_path)
                    except Exception:
                        pass

                    item.url = final_url
                    item.path = final_path
                    item.name = os.path.basename(final_path) or item.name

                    item.total = int(resp.headers.get("Content-Length", 0) or 0)
                    item.contentType = content_type
                    item.type = item.contentType

                    async with aiofiles.open(part_path, mode="wb") as f:
                        item.received = 0
                        stop_hits = 0
                        sample_every = 4
                        chunk_idx = 0
                        async for chunk in resp.content.iter_chunked(16384):
                            # Sample periodically and require repeated stop breaches.
                            # This avoids failing writes from one transient cpu spike.
                            chunk_idx += 1
                            if chunk_idx % sample_every == 0:
                                cpu, mem = self.resource_governor.get_usage()
                                if cpu >= self.resource_governor.config.pause_cpu or mem >= self.resource_governor.config.pause_mem:
                                    await asyncio.sleep(0.08)
                                if cpu >= self.resource_governor.config.stop_cpu or mem >= self.resource_governor.config.stop_mem:
                                    stop_hits += 1
                                else:
                                    stop_hits = 0
                                if stop_hits >= 5:
                                    raise ResourceOverloaded(
                                        f"Resource stop triggered repeatedly (cpu={cpu:.1f}%, mem={mem:.1f}%)"
                                    )
                            await f.write(chunk)
                            item.received += len(chunk)
                            if self.ws_callback:
                                await self.ws_callback({"type": "progress", "data": item.dict()})

                os.replace(part_path, item.path)
                item.state = "completed"
                item.error = None
                async with self._state_lock:
                    self._processed_urls.add(item.url)

                if self.ws_callback:
                    await self.ws_callback({"type": "completed", "data": item.dict()})

                ct = (item.contentType or "").lower()
                if "text/css" in ct or item.path.lower().endswith(".css"):
                    await self._rewrite_css_file(item)

            except ResourceOverloaded:
                # Immediate stop: keep the job and requeue it after we recover.
                try:
                    if os.path.exists(item.path + ".part"):
                        os.remove(item.path + ".part")
                except Exception:
                    pass
                item.state = "pending"
                item.error = None
                global_logger.warn(
                    f"[StopNow] Overload detected. Requeuing: {item.name} ({item.url})"
                )
                if self.ws_callback:
                    await self.ws_callback({"type": "progress", "data": item.dict()})

                await self.resource_governor.wait_until_resume()
                await self._asset_queue.put(job)

            except Exception as e:
                try:
                    if os.path.exists(item.path + ".part"):
                        os.remove(item.path + ".part")
                except Exception:
                    pass
                item.state = "error"
                item.error = str(e)
                global_logger.error(f"Asset failed: {item.name} - {e}")
                if self.ws_callback:
                    await self.ws_callback({"type": "error", "id": item.id, "error": str(e)})

            finally:
                self._asset_queue.task_done()

    async def _html_worker(self, worker_idx: int) -> None:
        while True:
            job = await self._html_queue.get()
            item = self.downloads.get(job.id)
            if not item:
                self._html_queue.task_done()
                continue

            try:
                global_logger.info(f"[*] HTML worker {worker_idx} picked job: {item.url}")
                await self.resource_governor.wait_for_capacity()
                async with self._state_lock:
                    item.state = "downloading"
                    item.error = None
                    # Reserve the session for HTML jobs: we count them to avoid runaway crawling.
                    if job.html_depth == 0:
                        # root page
                        pass

                    if self.ws_callback:
                        await self.ws_callback({"type": "progress", "data": item.dict()})

                global_logger.info(f"[*] HTML worker {worker_idx} hydrating: {item.url}")

                if not self.browser_manager:
                    raise RuntimeError("browser_manager not set")

                try:
                    await self.browser_manager.hydrate(item.id, job.url)
                except Exception as hydration_err:
                    global_logger.warn(f"[*] Hydration failed for {item.url}, falling back to raw download: {hydration_err}")
                    try:
                        async with self._http_session.get(item.url) as response:
                            if response.status == 200:
                                content = await response.text(errors="ignore")
                                # Manually save and skip standard completion logic as save_content_to_item handles it
                                await self.save_content_to_item(item.id, item.url, content, "text/html")
                            else:
                                raise RuntimeError(f"Fallback GET failed with status {response.status}")
                    except Exception as fallback_err:
                        # If both fail, then we really have an error
                        raise RuntimeError(f"Hydration failed ({hydration_err}) and Fallback failed ({fallback_err})")

                async with self._state_lock:
                    self._html_processed_count += 1

            except ResourceOverloaded:
                item.state = "pending"
                item.error = None
                global_logger.warn(
                    f"[StopNow] Overload detected. Requeuing HTML: {item.name} ({item.url})"
                )
                if self.ws_callback:
                    await self.ws_callback({"type": "progress", "data": item.dict()})

                await self.resource_governor.wait_until_resume()
                await self._html_queue.put(job)

            except Exception as e:
                item.state = "error"
                item.error = str(e)
                global_logger.error(f"HTML failed: {item.name} - {e}")
                if self.ws_callback:
                    await self.ws_callback({"type": "error", "id": item.id, "error": str(e)})

            finally:
                self._html_queue.task_done()

    async def download(self, url: str, headers: Optional[Dict[str, str]] = None):
        content_type = ""
        if headers:
            content_type = headers.get("content-type") or headers.get("Content-Type") or ""
        return await self.start_download(url, content_type)


download_manager = DownloadManager()
