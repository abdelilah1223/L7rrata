from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
import os
import subprocess
from pydantic import BaseModel
from typing import List, Optional, Set
import json
import asyncio
from browser import browser_manager, DeepData
from downloader_queue import download_manager, DownloadItem
from scraper import scrape_page
from proxy import proxy_request
from logger import global_logger
import dataclasses
import asyncio
from playwright.async_api import async_playwright

router = APIRouter()

# External login browser instance (singleton pattern)
_external_login_browser = None
_external_login_context = None
_external_login_page = None

# WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# Settings persistence
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
def load_settings():
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                return json.load(f)
        except Exception: pass
    return {
        "maxFileSize": 50 * 1024 * 1024,
        "autoDownload": True,
        "proxy": {"enabled": False, "type": "http", "host": "", "port": "", "username": "", "password": ""}
    }

def save_settings(s):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=4)

class BrowserCommand(BaseModel):
    command: Optional[str] = None
    url: Optional[str] = None
    tab_id: Optional[str] = None

    class Config:
        extra = "allow"

class DownloadRequest(BaseModel):
    url: str
    content_type: Optional[str] = ""

async def ws_broadcast_progress(msg: dict):
    await manager.broadcast(msg)

async def handle_deep_data(data: DeepData, tab_id: str):
    try:
        msg = {
            "type": "deep_data",
            "tab_id": tab_id,
            "data": {
                "url": data.url,
                "method": data.method,
                "status": data.status,
                "content_type": data.content_type,
                "response": data.response_body,
                "request": data.request_body
            }
        }
        await manager.broadcast(msg)
    except Exception as e:
        global_logger.error(f"Error broadcasting deep data: {e}")

@router.on_event("startup")
async def startup_event():
    download_manager.ws_callback = ws_broadcast_progress
    download_manager.browser_manager = browser_manager
    browser_manager.set_download_manager(download_manager)
    browser_manager.set_resource_governor(download_manager.resource_governor)
    browser_manager.on_deep_data = handle_deep_data
    await download_manager.start_workers()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Sync any existing downloads so the UI doesn't miss updates
    # if jobs were enqueued before the WS connection was established.
    try:
        existing = list(download_manager.downloads.values())
        # Cap to keep connection burst reasonable.
        for item in existing[-500:]:
            await websocket.send_json({"type": "progress", "data": item.dict()})
    except Exception:
        pass
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@router.get("/status")
async def get_status():
    return {"status": "ok", "message": "Backend is running"}

@router.get("/downloads", response_model=List[DownloadItem])
async def get_downloads():
    return list(download_manager.downloads.values())

@router.post("/download")
async def start_new_download(req: DownloadRequest):
    # Ensure queue workers are alive before accepting jobs.
    await download_manager.start_workers()
    item = await download_manager.start_download(req.url, req.content_type)
    return item

@router.post("/downloads/{download_id}/open")
async def open_download_folder(download_id: str):
    item = download_manager.downloads.get(download_id)
    if not item or not os.path.exists(item.path):
        return {"success": False}
    # Windows Explorer expects `/select,<path>` in a single argument.
    subprocess.run(['explorer', f'/select,{os.path.normpath(item.path)}'])
    return {"success": True}

@router.delete("/downloads/{download_id}/delete")
async def delete_download(download_id: str):
    item = download_manager.downloads.get(download_id)
    if item:
        if os.path.exists(item.path):
            try: os.remove(item.path)
            except Exception: pass
        del download_manager.downloads[download_id]
    return {"success": True}

@router.get("/proxy")
async def proxy_url(url: str, request: Request):
    return await proxy_request(url, request)

@router.post("/browser")
async def browser_control(request: Request):
    try:
        body = await request.json()
        global_logger.info(f"[*] Browser API Request: {body}")
        
        # Manually parse to avoid strict 422
        command = body.get("command")
        url = body.get("url")
        tab_id = str(body.get("tab_id", "default"))

        await browser_manager.start()
        
        if command == "navigate":
            success = await browser_manager.navigate(url, tab_id)
            if not success:
                return {"status": "failed"}

            # Ensure the "main document" HTML is also saved + rewritten.
            # Important: enqueue into the HTML worker so overload can requeue safely.
            try:
                settings = load_settings()
                if settings.get("autoDownload", True) and url and url.startswith("http"):
                    await download_manager.start_workers()
                    await download_manager.enqueue_html(url, depth=0)
            except Exception as e:
                global_logger.warn(f"[HTML Enqueue] Failed for {url}: {e}")

            return {"status": "navigating"}
        elif command == "refresh":
            await browser_manager.refresh(tab_id)
            return {"status": "refreshing"}
        elif command == "scrape":
            page = browser_manager.pages.get(tab_id or browser_manager.current_page_id)
            if page:
                data = await scrape_page(page)
                return {"status": "success", "data": data}
            raise HTTPException(status_code=400, detail="Page not found")
        return {"status": "received"}
    except Exception as e:
        global_logger.error(f"Browser API Error: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/settings")
async def get_settings_api():
    return load_settings()

@router.post("/external-login/start")
async def start_external_login(request: Request):
    """
    Launch a visible Playwright browser for external login.
    Cookies will be synced back to the main browser context.
    """
    global _external_login_browser, _external_login_context, _external_login_page
    
    try:
        body = await request.json()
        url = body.get("url", "")
        
        # Close any existing external login browser
        await stop_external_login()
        
        # Launch visible browser for login
        playwright = await async_playwright().start()
        _external_login_browser = await playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--start-maximized",
                "--window-size=1280,800"
            ]
        )
        
        _external_login_context = await _external_login_browser.new_context(
            viewport=None  # Use maximized window
        )
        _external_login_page = await _external_login_context.new_page()
        
        if url and url.startswith("http"):
            await _external_login_page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        return {"status": "opened", "message": "Login browser opened. Cookies will sync automatically."}
    except Exception as e:
        global_logger.error(f"External login start error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/external-login/sync-cookies")
async def sync_external_login_cookies():
    """
    Sync cookies from external login browser to main browser context.
    Called periodically by Electron or on browser close.
    """
    global _external_login_browser, _external_login_context, _external_login_page
    
    try:
        if not _external_login_context or not browser_manager._browser:
            return {"status": "no_browser", "cookies": []}
        
        # Get cookies from external login context
        cookies = await _external_login_context.cookies()
        
        # Add cookies to main browser manager contexts
        # Note: Playwright contexts are isolated, so we store for reference
        # The actual cookie sync happens via Electron's session
        
        return {
            "status": "synced",
            "cookies": [
                {
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "domain": c.get("domain"),
                    "path": c.get("path", "/"),
                    "secure": c.get("secure", False),
                    "httpOnly": c.get("httpOnly", False),
                    "sameSite": c.get("sameSite", "Lax"),
                    "expires": c.get("expires")
                }
                for c in cookies
            ]
        }
    except Exception as e:
        global_logger.error(f"Cookie sync error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/external-login/stop")
async def stop_external_login():
    """
    Close the external login browser.
    """
    global _external_login_browser, _external_login_context, _external_login_page
    
    try:
        if _external_login_page:
            await _external_login_page.close()
            _external_login_page = None
        if _external_login_context:
            await _external_login_context.close()
            _external_login_context = None
        if _external_login_browser:
            await _external_login_browser.close()
            _external_login_browser = None
        return {"status": "closed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/external-login/status")
async def get_external_login_status():
    """
    Check if external login browser is running.
    """
    is_running = _external_login_browser is not None
    return {"running": is_running}


@router.post("/settings")
async def save_settings_api(settings: dict):
    save_settings(settings)
    return {"success": True}
