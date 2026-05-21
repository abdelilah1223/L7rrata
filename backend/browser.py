import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, Page, Playwright, Response
import json

from resource_governor import ResourceGovernor, ResourceOverloaded, QualityMode


@dataclass(frozen=True)
class DeepData:
    url: str
    method: str
    status: int
    content_type: str
    response_body: Any
    request_body: Optional[Any] = None


@dataclass(frozen=True)
class HydrateResult:
    html: str
    final_url: str


class BrowserManager:
    """
    Minimal Playwright wrapper for:
    - page navigation (used by the API)
    - HTML hydration (page.content()) which is then saved by DownloadManager
    - Network interception for deep data analysis (JSON/GraphQL)

    This module intentionally blocks heavy resources when CPU/RAM are high
    to reduce the risk of freezing the PC.
    """

    def __init__(self):
        self._start_lock = asyncio.Lock()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

        self.pages: Dict[str, Page] = {}
        self.current_page_id: Optional[str] = None

        self.download_manager: Any = None
        self.resource_governor: Optional[ResourceGovernor] = None

        # Hydration is expensive; serialize to keep memory/CPU bounded.
        self._hydrate_lock = asyncio.Lock()

        # Callback for deep data (JSON/GraphQL)
        self.on_deep_data: Optional[callable] = None

    def set_download_manager(self, download_manager: Any) -> None:
        self.download_manager = download_manager

    def set_resource_governor(self, governor: ResourceGovernor) -> None:
        self.resource_governor = governor

    async def start(self) -> None:
        async with self._start_lock:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()

            # Chromium args: keep it light and avoid GPU-related overhead.
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

    def _get_quality(self) -> QualityMode:
        if not self.resource_governor:
            return "mid"
        return self.resource_governor.quality()

    async def _route_handler(self, route) -> None:
        try:
            rtype = route.request.resource_type
        except Exception:
            await route.continue_()
            return

        quality = self._get_quality()

        # Block heavy resources more aggressively under load.
        if quality == "low":
            # Extreme load: block all non-essential assets for analysis.
            if rtype in {"image", "media", "font"}:
                await route.abort()
                return
        elif quality == "mid":
            # Moderate load: block heavy media (video/audio) but allow images and fonts.
            if rtype in {"media"}:
                await route.abort()
                return
        # quality == "high": allow everything for full analysis.
        await route.continue_()

    async def navigate(self, url: str, tab_id: str = "default") -> bool:
        await self.start()
        if not url:
            return False
        context = await self._browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        await page.route("**/*", self._route_handler)
        await page.goto(url, wait_until="domcontentloaded")

        self.pages[tab_id] = page
        self.current_page_id = tab_id

        # Setup response interception for deep data
        page.on("response", lambda res: asyncio.create_task(self._handle_response(res, tab_id)))

        return True

    async def _handle_response(self, response: Response, tab_id: str) -> None:
        """
        Intercepts responses to capture JSON/GraphQL data.
        """
        try:
            url = response.url
            if not url or url.startswith("data:") or "127.0.0.1" in url or "localhost" in url:
                return

            headers = response.headers
            content_type = headers.get("content-type", "").lower()

            if "application/json" in content_type:
                # Capture the JSON body if it's not too large
                try:
                    # We use a timeout to avoid hangs on large or slow streams
                    body = await response.json()
                    
                    # Also capture request body (post_data) if it's a POST
                    request = response.request
                    request_body = None
                    if request.method == "POST":
                        try:
                            post_data = request.post_data
                            if post_data:
                                try:
                                    request_body = json.loads(post_data)
                                except Exception:
                                    request_body = post_data
                        except Exception:
                            pass

                    deep_data = DeepData(
                        url=url,
                        method=request.method,
                        status=response.status,
                        content_type=content_type,
                        response_body=body,
                        request_body=request_body
                    )

                    if self.on_deep_data:
                        await self.on_deep_data(deep_data, tab_id)

                except Exception:
                    # Failed to parse JSON or get body (common for aborted or large responses)
                    pass

        except Exception:
            pass

    async def refresh(self, tab_id: str = "default") -> None:
        await self.start()
        page = self.pages.get(tab_id) or self.pages.get(self.current_page_id or "")
        if not page:
            return
        await page.reload(wait_until="domcontentloaded")

    def _find_existing_page(self, url: str) -> Optional[Page]:
        target = (url or "").rstrip("/")
        if not target:
            return None

        for page in self.pages.values():
            try:
                current = (page.url or "").rstrip("/")
                if current == target:
                    return page
            except Exception:
                continue
        return None

    async def _capture_page_state(self, item_id: str, page: Page, fallback_url: str) -> HydrateResult:
        html = await page.content()
        final_url = page.url or fallback_url

        extracted = None
        try:
            quality = self._get_quality()
            extract_inline = quality != "low"
            max_inline = 5 if quality == "mid" else 15
            max_bytes = 8 * 1024 * 1024
            extracted = await page.evaluate(
                """({ maxInline, maxBytes, extractInline, apolloKeyLimit }) => {
  const wrapTrunc = (prefix, approxBytes, maxBytes) => ({
    __truncated__: true,
    __maxBytes__: maxBytes,
    __approxBytes__: approxBytes,
    preview: prefix
  });

  const tryParse = (txt) => {
    try { return JSON.parse(txt); } catch (e) { return null; }
  };

  let next_data = null;
  try {
    const el = document.getElementById('__NEXT_DATA__');
    if (el) {
      const txt = el.textContent || '';
      if (txt.length <= maxBytes) {
        const parsed = tryParse(txt);
        if (parsed) next_data = parsed;
        else next_data = { __unparsed__: true, text: txt.slice(0, 2000) };
      } else {
        next_data = wrapTrunc(txt.slice(0, 4000), txt.length, maxBytes);
      }
    } else if (window && window.__NEXT_DATA__) {
      const approx = JSON.stringify(window.__NEXT_DATA__).length;
      if (approx <= maxBytes) next_data = window.__NEXT_DATA__;
      else next_data = wrapTrunc(String(approx), approx, maxBytes);
    }
  } catch (e) {}

  let apollo_state = null;
  try {
    if (window && window.__APOLLO_STATE__) {
      const state = window.__APOLLO_STATE__;
      const keys = Object.keys(state || {});
      if (keys.length > apolloKeyLimit) {
        apollo_state = {
          __truncated__: true,
          __maxBytes__: maxBytes,
          __reason__: "too_many_top_level_keys",
          topLevelKeys: keys.slice(0, 50)
        };
      } else {
        const txt = JSON.stringify(state);
        if (txt.length <= maxBytes) apollo_state = state;
        else apollo_state = wrapTrunc(txt.slice(0, 4000), txt.length, maxBytes);
      }
    }
  } catch (e) {}

  const inline_application_json = [];
  if (extractInline) {
    try {
      const scripts = Array.from(document.querySelectorAll('script[type=\"application/json\"]'));
      for (let i = 0; i < Math.min(scripts.length, maxInline); i++) {
        const s = scripts[i];
        const id = s.id || null;
        const txt = s.textContent || '';
        if (txt.length > 0) {
          if (txt.length <= maxBytes) {
            const parsed = tryParse(txt);
            if (parsed !== null) inline_application_json.push({ index: i, id, data: parsed });
            else inline_application_json.push({ index: i, id, data: { __unparsed__: true, text: txt.slice(0, 2000) }});
          } else {
            inline_application_json.push({ index: i, id, data: wrapTrunc(txt.slice(0, 4000), txt.length, maxBytes) });
          }
        }
      }
    } catch (e) {}
  }

  return { next_data, apollo_state, inline_application_json };
}""",
                {
                    "maxInline": max_inline,
                    "maxBytes": max_bytes,
                    "extractInline": extract_inline,
                    "apolloKeyLimit": 2000,
                },
            )
        except Exception:
            extracted = None

        await self.download_manager.save_content_to_item(
            item_id=item_id,
            url=final_url,
            content=html,
            content_type="text/html",
        )

        if extracted:
            try:
                await self.download_manager.save_extracted_page_state(final_url, extracted)
            except Exception:
                pass

        return HydrateResult(html=html, final_url=final_url)

    async def _goto_with_stop(self, page: Page, url: str) -> None:
        """
        Runs page.goto while simultaneously watching CPU/RAM.
        If stop thresholds are exceeded, closes the page and raises ResourceOverloaded.
        """
        if not self.resource_governor:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return

        stop_exc: Optional[Exception] = None

        async def monitor() -> None:
            nonlocal stop_exc
            while True:
                try:
                    self.resource_governor.check_or_raise()
                except Exception as e:
                    stop_exc = e
                    try:
                        await page.close()
                    except Exception:
                        pass
                    return
                await asyncio.sleep(self.resource_governor.config.poll_interval_s)

        goto_task = asyncio.create_task(
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        )
        monitor_task = asyncio.create_task(monitor())

        try:
            await goto_task
        finally:
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await monitor_task

        if stop_exc is not None:
            if isinstance(stop_exc, ResourceOverloaded):
                raise stop_exc
            raise ResourceOverloaded(str(stop_exc))

    async def hydrate(self, item_id: str, url: str) -> HydrateResult:
        await self.start()
        async with self._hydrate_lock:
            if not self.download_manager:
                raise RuntimeError("BrowserManager.download_manager is not set")

            if not self.resource_governor:
                # Still hydrate but with reduced blocking defaults.
                self.resource_governor = ResourceGovernor()

            existing_page = self._find_existing_page(url)
            if existing_page is not None:
                return await self._capture_page_state(item_id, existing_page, url)

            context = await self._browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(60000)

            await page.route("**/*", self._route_handler)
            page.on("response", lambda res: asyncio.create_task(self._handle_response(res, "hydrate")))

            try:
                # Navigation may be blocked by hard-load sites; keep it bounded.
                try:
                    await self._goto_with_stop(page, url)
                except Exception as exc:
                    message = str(exc).lower()
                    if page.url and page.url != "about:blank" and (
                        "err_aborted" in message
                        or "frame was detached" in message
                        or "navigation failed because page was closed" in message
                    ):
                        pass
                    else:
                        raise

                return await self._capture_page_state(item_id, page, url)
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass


browser_manager = BrowserManager()
