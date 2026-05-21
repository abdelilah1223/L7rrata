import asyncio
import aiohttp
import aiofiles
import os
import uuid
import time
from urllib.parse import urlparse, unquote, urljoin
from typing import Dict, Optional
import datetime
from pydantic import BaseModel
from logger import global_logger
from bs4 import BeautifulSoup

class DownloadItem(BaseModel):
    id: str
    url: str
    name: str
    path: str
    total: int
    received: int
    state: str # pending, downloading, completed, error
    error: Optional[str] = None
    startTime: float
    contentType: Optional[str] = ""

class DownloadManager:
    def __init__(self, base_dir=None):
        if base_dir is None:
            self.base_dir = "c:/2em/nodejs/web-downloader/python-version/downloads"
        else:
            self.base_dir = base_dir
            
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir, exist_ok=True)
            
        self.downloads: Dict[str, DownloadItem] = {}
        self.processed_urls: Set[str] = set()
        self.ws_callback = None # Function to call for progress updates
        self.browser_manager = None # Linked during startup in api.py

    def _should_skip(self, url: str, file_path: str):
        """Checks if a URL should be skipped based on processed_urls or file state."""
        if url not in self.processed_urls:
            return False
            
        # If it's in processed_urls but the file is missing or empty, don't skip
        if not os.path.exists(file_path):
            return False
        
        if os.path.getsize(file_path) == 0:
            global_logger.info(f"[Retry] File is empty, re-downloading: {url}")
            return False
            
        return True

    def sanitize_filename(self, name: str):
        """Strips illegal characters and truncates to avoid Windows path limits."""
        # Illegal: < > : " / \ | ? * ( )
        chars = '<>:"/\\|?*()'
        for char in chars:
            name = name.replace(char, '_')
        
        # Windows filename length limit is 255, but full path limit is 260.
        # Truncating to 100 is safe.
        name = name.strip()
        if len(name) > 100:
            ext = os.path.splitext(name)[1]
            name = name[:90] + "_trunc" + ext
            
        return name

    def get_target_root(self, url: str):
        """Creates the domain_date root folder."""
        d = datetime.datetime.now()
        date_str = d.strftime("%d_%m_%Y")
        parsed = urlparse(url)
        hostname = self.sanitize_filename(parsed.hostname.replace('www.', '') if parsed.hostname else 'misc')
        return os.path.join(self.base_dir, f"{hostname}_{date_str}")

    def get_mirror_path(self, target_root: str, url: str, content_type: str = ""):
        """Mirrors the original URL path structure with category subfolders."""
        # Safety: Clean incoming URL of any CSS wrappers if regex leaked them
        url = url.strip().strip('"').strip("'")
        if url.lower().startswith('url('):
            url = url[4:].rstrip(')')
        url = url.strip().strip('"').strip("'")
        
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1].lower()
        ct = content_type.lower()
        
        # 1. Determine Category
        category = ""
        if any(x in ct for x in ["image/", "image"]) or ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico"]:
            category = "images"
        elif any(x in ct for x in ["video/", "video"]) or ext in [".mp4", ".webm", ".m4v", ".m3u8", ".ts"]:
            category = "videos"
        elif any(x in ct for x in ["audio/", "audio"]) or ext in [".mp3", ".wav", ".ogg", ".aac"]:
            category = "audio"
        elif "javascript" in ct or ext == ".js":
            category = "js"
        elif "css" in ct or ext == ".css":
            category = "css"
        
        # 2. Handle Filename
        filename = os.path.basename(path)
        if not filename or path.endswith('/') or not ext:
            filename = "index.html"
        
        filename = self.sanitize_filename(filename)
        
        # For clean URLs/folders, ensure index.html
        if not os.path.splitext(filename)[1] and category == "":
            filename += ".html"
            
        # 3. Build Final Path
        if category:
            full_path = os.path.join(target_root, category, filename)
        else:
            # For HTML/Others, keep original path but relative to root
            # STRIP TRAILING SLASH to avoid folder vs file collision
            rel_dir = os.path.dirname(path.lstrip('/'))
            full_path = os.path.join(target_root, rel_dir, filename)
            
        # NORMALIZE PATH for Windows
        full_path = os.path.normpath(full_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        return full_path

    def get_local_rel_path(self, link_url, current_page_url, current_page_path):
        """Shared helper to calculate relative path for mirroring."""
        if not link_url or link_url.startswith(('#', 'data:', 'javascript:', 'mailto:', 'tel:')):
            return None
        
        # Clean URL if it's wrapped in CSS url()
        link_url = link_url.strip().strip('"').strip("'").strip()
        if link_url.lower().startswith('url('):
            link_url = link_url[4:].rstrip(')').strip().strip('"').strip("'")

        # Join with base if relative to original page
        absolute_url = urljoin(current_page_url, link_url)
        parsed_abs = urlparse(absolute_url)
        parsed_base = urlparse(current_page_url)
        
        target_root = self.get_target_root(current_page_url)
        
        # Determine target file location
        if parsed_abs.hostname != parsed_base.hostname and parsed_abs.hostname:
            # Save in external/hostname/path
            ext_root = os.path.join(target_root, "external", parsed_abs.hostname)
            target_file = self.get_mirror_path(ext_root, absolute_url)
        else:
            # Save in local root
            target_file = self.get_mirror_path(target_root, absolute_url)
        
        rel_path = os.path.relpath(target_file, os.path.dirname(current_page_path))
        return rel_path.replace('\\', '/')

    async def start_download(self, url: str, content_type: str = ""):
        target_root = self.get_target_root(url)
        # Prediction of path for skipping logic
        temp_path = self.get_mirror_path(target_root, url, content_type)
        if self._should_skip(url, temp_path):
            return None
            
        # Hydration Logic: If internal HTML, use background browser
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1].lower()
        
        # REFINED HYDRATION FILTER
        # Don't hydrate if:
        # 1. Ext is clearly an asset
        # 2. Hostname looks like a CDN (static., scontent., fbcdn.)
        cdn_keywords = [".fbcdn.", "static.", "scontent.", "cdn.", "images.", "assets."]
        is_cdn = any(k in parsed.hostname.lower() for k in cdn_keywords) if parsed.hostname else False
        
        is_html = not ext or ext in [".html", ".php", ".asp", ".aspx", ".jsp"] or "text/html" in content_type.lower()
        
        if (self.browser_manager and is_html and not is_cdn and url.startswith("http")):
            self.processed_urls.add(url)
            asyncio.create_task(self.browser_manager.hydrate(url))
            return None

        # Standard download for assets/external
        self.processed_urls.add(url)
            
        id = str(uuid.uuid4())
        file_path = temp_path
        
        item = DownloadItem(
            id=id,
            url=url,
            name=os.path.basename(file_path),
            path=file_path,
            total=0,
            received=0,
            state="pending",
            startTime=time.time(),
            contentType=content_type
        )
        self.downloads[id] = item
        global_logger.info(f"[*] NEW DOWNLOAD: {url} -> {os.path.relpath(file_path, self.base_dir)}")
        
        asyncio.create_task(self._run_download(id))
        return item

    async def save_asset(self, url: str, content: bytes, content_type: str = ""):
        """Saves binary/text content directly (e.g., from Playwright response.body())."""
        target_root = self.get_target_root(url)
        file_path = self.get_mirror_path(target_root, url, content_type)
        
        if self._should_skip(url, file_path):
            return
            
        self.processed_urls.add(url)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Write content
        mode = "wb" if isinstance(content, bytes) else "w"
        encoding = None if isinstance(content, bytes) else "utf-8"
        
        async with aiofiles.open(file_path, mode=mode, encoding=encoding) as f:
            await f.write(content)
            
        global_logger.info(f"[Captured] {url} -> {os.path.basename(file_path)} ({len(content)} bytes)")
        
        # Post-process if CSS
        if "text/css" in content_type.lower() or file_path.endswith(".css"):
            id = str(uuid.uuid4())
            item = DownloadItem(id=id, url=url, name=os.path.basename(file_path), path=file_path, total=len(content), received=len(content), state="completed", startTime=time.time(), contentType=content_type)
            self.downloads[id] = item
            asyncio.create_task(self._rewrite_css(item))

    async def save_content(self, url: str, content: str, content_type: str = "text/html"):
        """Saves hydrated content directly (e.g., from Playwright DOM) without a new fetch."""
        target_root = self.get_target_root(url)
        file_path = self.get_mirror_path(target_root, url, content_type)
        
        # For primary HTML, we might want to update it even if seen
        if url in self.processed_urls and os.path.exists(file_path) and os.path.getsize(file_path) > 100:
             if not content_type.startswith("text/html"):
                 return
        
        self.processed_urls.add(url)
            
        id = str(uuid.uuid4())
        item = DownloadItem(
            id=id,
            url=url,
            name=os.path.basename(file_path),
            path=file_path,
            total=len(content),
            received=len(content),
            state="completed",
            startTime=time.time(),
            contentType=content_type
        )
        self.downloads[id] = item
        
        async with aiofiles.open(file_path, mode="w", encoding="utf-8", errors="ignore") as f:
            await f.write(content)
            
        global_logger.info(f"[*] SAVED HYDRATED CONTENT: {url} -> {os.path.basename(file_path)}")
        
        if "text/html" in content_type.lower():
            asyncio.create_task(self._rewrite_links(item))
        
        if self.ws_callback:
            await self.ws_callback({"type": "completed", "data": item.dict()})
        return item

    async def _run_download(self, id: str):
        item = self.downloads[id]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(item.url, timeout=30, allow_redirects=True) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    
                    # FOLLOW REDIRECTS: Update info if URL changed
                    if str(response.url) != item.url:
                        new_url = str(response.url)
                        global_logger.info(f"[Redirect] {item.url} -> {new_url}")
                        item.url = new_url
                        # Re-calc path for final location
                        target_root = self.get_target_root(new_url)
                        item.path = self.get_mirror_path(target_root, new_url, response.headers.get("Content-Type", ""))
                        # Ensure the new path's directory exists
                        os.makedirs(os.path.dirname(item.path), exist_ok=True)

                    item.contentType = response.headers.get("Content-Type", item.contentType)
                    item.total = int(response.headers.get("Content-Length", 0))
                    item.state = "downloading"
                    
                    async with aiofiles.open(item.path, mode="wb") as f:
                        async for chunk in response.content.iter_chunked(16384):
                            await f.write(chunk)
                            item.received += len(chunk)
                            if self.ws_callback:
                                await self.ws_callback({"type": "progress", "data": item.dict()})
                    
                    item.state = "completed"
                    
                    # Post-process HTML/CSS for link rewriting
                    ct = (item.contentType or "").lower()
                    if "text/html" in ct:
                        await self._rewrite_links(item)
                    elif "text/css" in ct:
                        await self._rewrite_css(item)
                        
                    global_logger.info(f"Success: {item.name}")
                    if self.ws_callback:
                        await self.ws_callback({"type": "completed", "data": item.dict()})
                        
        except Exception as e:
            item.state = "error"
            item.error = str(e)
            global_logger.error(f"Failed: {item.name} - {e}")
            if self.ws_callback:
                await self.ws_callback({"type": "error", "id": id, "error": str(e)})

    async def _rewrite_links(self, item: DownloadItem):
        """Rewrites <a>, <img>, <link>, <script> tags to use local relative paths."""
        try:
            async with aiofiles.open(item.path, mode="r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()
            
            soup = BeautifulSoup(content, 'lxml')
            
            # Handle <base> tag
            base_tag = soup.find('base', href=True)
            page_base_url = urljoin(item.url, base_tag['href']) if base_tag else item.url

            # Rewrite & Spider tags
            # Added source, track, embed, use for comprehensive asset capture
            asset_tags = [
                ('a', 'href'), ('img', 'src'), ('link', 'href'), ('script', 'src'),
                ('source', 'src'), ('track', 'src'), ('embed', 'src'), ('use', 'xlink:href'),
                ('object', 'data')
            ]
            for tag, attr in asset_tags:
                for el in soup.find_all(tag, **{attr: True}):
                    link_url = el[attr]
                    new_val = self.get_local_rel_path(link_url, page_base_url, item.path)
                    if new_val:
                        el[attr] = new_val
                        # SPIDER: Trigger download for linked resources
                        abs_url = urljoin(page_base_url, link_url)
                        if tag == 'a':
                            # Recursive crawl: Only same-domain to avoid infinite loops
                            parsed_abs = urlparse(abs_url)
                            parsed_base = urlparse(item.url)
                            if parsed_abs.hostname == parsed_base.hostname:
                                asyncio.create_task(self.start_download(abs_url))
                        else:
                            # Direct asset download
                            asyncio.create_task(self.start_download(abs_url))
            
            # DEEP CSS PARSING: Handle <style> tags and @import
            import re
            style_pattern = re.compile(r'url\((["\']?)([^)]+)\1\)|@import\s+(["\']?)([^;]+)\3', re.I)
            for style_tag in soup.find_all('style'):
                css_content = style_tag.string or ""
                def css_replace(match):
                    raw_wrapper = match.group(0)
                    url = match.group(2) or match.group(4)
                    if url:
                        new_rel = self.get_local_rel_path(url, page_base_url, item.path)
                        if new_rel:
                            # Start asset download
                            abs_url = urljoin(page_base_url, url)
                            asyncio.create_task(self.start_download(abs_url))
                            return raw_wrapper.replace(url, new_rel)
                    return raw_wrapper
                
                style_tag.string = style_pattern.sub(css_replace, css_content)
            
            async with aiofiles.open(item.path, mode="w", encoding="utf-8") as f:
                await f.write(str(soup))
                
        except Exception as e:
            global_logger.warn(f"Link rewriting failed for {item.name}: {e}")

    async def _rewrite_css(self, item: DownloadItem):
        """Rewrites url() and @import in standalone .css files."""
        try:
            async with aiofiles.open(item.path, mode="r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()
            
            import re
            style_pattern = re.compile(r'url\((["\']?)([^)]+)\1\)|@import\s+(["\']?)([^;]+)\3', re.I)
            
            def css_replace(match):
                raw_wrapper = match.group(0)
                url = match.group(2) or match.group(4)
                if url:
                    new_rel = self.get_local_rel_path(url, item.url, item.path)
                    if new_rel:
                        abs_url = urljoin(item.url, url)
                        asyncio.create_task(self.start_download(abs_url))
                        return raw_wrapper.replace(url, new_rel)
                return raw_wrapper
            
            new_content = style_pattern.sub(css_replace, content)
            async with aiofiles.open(item.path, mode="w", encoding="utf-8") as f:
                await f.write(new_content)
                
        except Exception as e:
            global_logger.warn(f"CSS rewriting failed for {item.name}: {e}")

    async def download(self, url, headers=None):
        content_type = ""
        if headers:
            content_type = headers.get("content-type") or headers.get("Content-Type") or ""
        return await self.start_download(url, content_type)

download_manager = DownloadManager()
