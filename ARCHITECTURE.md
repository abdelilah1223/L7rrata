# Web Downloader Architecture

## Overview

This project implements a **dual-Chromium architecture** where:
- **Electron** provides the UI using Chromium
- **Python + Playwright** handles headless scraping using another Chromium instance

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ELECTRON APP                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  BrowserWindow (Chromium #1 - UI Display)                         │    │
│  │  ├── React UI (Controls, Download List, Settings)                   │    │
│  │  └── Webview Tag (Embedded browser for viewing websites)          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  IPC Main Process (Node.js)                                         │    │
│  │  ├── Handles UI → Backend communication                             │    │
│  │  ├── WebSocket client (receives real-time updates)                │    │
│  │  └── net.fetch() (HTTP API calls to Python)                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ WebSocket + HTTP (localhost:8000)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PYTHON BACKEND                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  FastAPI Server                                                     │    │
│  │  ├── HTTP Routes (/api/*)                                           │    │
│  │  ├── WebSocket Endpoint (/api/ws)                                   │    │
│  │  └── Static File Serving (frontend/dist in production)              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  BrowserManager (Playwright + Chromium #2 - Headless)                 │    │
│  │  ├── Page navigation                                                │    │
│  │  ├── Network interception (API scraping)                              │    │
│  │  ├── HTML hydration (page.content())                                │    │
│  │  └── Resource extraction (images, videos, documents)                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  DownloadManager                                                    │    │
│  │  ├── Queue system with workers                                      │    │
│  │  ├── Concurrent downloads with limits                               │    │
│  │  ├── HTML rewriting (self-contained archives)                       │    │
│  │  └── Progress tracking & WebSocket broadcasts                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  External Login Browser (Playwright - Visible)                      │    │
│  │  ├── Headless=False browser for OAuth/login flows                 │    │
│  │  └── Cookie sync back to Electron session                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Why This Architecture?

### Electron = UI (Chromium #1)
- Displays the application interface
- Embeds webview for browsing
- Handles user interactions
- Manages native OS features (file dialogs, notifications)

### Playwright = Scraping Engine (Chromium #2)
- **Better API access**: `response.json()`, `request.post_data`
- **Network interception**: Captures all XHR/fetch requests
- **Headless operation**: Runs in background without UI
- **More reliable**: Better for automated data extraction

### Why not Electron's webRequest?
```javascript
// ❌ Electron webRequest limitations:
session.webRequest.onCompleted(...)
// - Doesn't give you response body
// - No easy access to JSON data
// - GraphQL responses are opaque

// ✅ Playwright advantages:
page.on('response', async response => {
    const json = await response.json();  // Direct access!
    const request = response.request();
    const postData = await request.post_data();  // Request body!
})
```

## Communication Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  User    │────►│  React   │────►│  IPC     │────►│  Python  │
│  Action  │     │  UI      │     │  Main    │     │  API     │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                                              
     ▲                                              │
     │                                              ▼
     │                                        ┌──────────┐
     └────────────────────────────────────────│ WebSocket│
          Real-time updates                   │ Broadcast│
                                              └──────────┘
```

### Key Communication Channels

| Channel | Protocol | Purpose |
|---------|----------|---------|
| `localhost:8000/api/*` | HTTP | Request-response operations |
| `localhost:8000/api/ws` | WebSocket | Real-time progress updates |
| `ipcRenderer` | Electron IPC | UI ↔ Main process |

## File Structure

```
python-version/
├── backend/
│   ├── main.py              # FastAPI server + webview log window
│   ├── api.py               # HTTP routes & WebSocket handler
│   ├── browser.py           # Playwright BrowserManager
│   ├── downloader_queue.py  # Download workers & queue
│   └── ...
├── frontend/
│   ├── src/
│   │   ├── main/
│   │   │   └── index.js     # Electron main process
│   │   ├── preload/
│   │   │   └── index.js     # Preload script (IPC bridge)
│   │   └── renderer/
│   │       └── ...          # React components
│   └── package.json         # Electron dependencies
└── start.py                 # Launcher script
```

## Starting the Application

### Development Mode
```bash
# Terminal 1: Start Python backend
python start.py

# Terminal 2: Start Electron dev
npm run electron
```

### Production Mode
```bash
# Build and package
npm run build
```

## Key Endpoints

### Browser Control
- `POST /api/browser` - Navigate, refresh, scrape pages

### Downloads
- `GET /api/downloads` - List all downloads
- `POST /api/download` - Start new download
- `DELETE /api/downloads/{id}/delete` - Remove download
- `POST /api/downloads/{id}/open` - Open file location

### External Login
- `POST /api/external-login/start` - Open visible browser for login
- `POST /api/external-login/sync-cookies` - Get cookies from login browser
- `POST /api/external-login/stop` - Close login browser
- `GET /api/external-login/status` - Check if login browser is running

### Settings
- `GET /api/settings` - Load settings
- `POST /api/settings` - Save settings

## Data Flow Example: Downloading a Website

1. **User enters URL** in Electron UI
2. **IPC sends** to Python: `POST /api/browser` (command: navigate)
3. **Playwright** launches headless Chromium, navigates to URL
4. **Network interception** captures all resources (JS, CSS, images, XHR)
5. **HTML hydration** gets full page content
6. **DownloadManager** queues all discovered resources
7. **Workers** download resources concurrently
8. **WebSocket** broadcasts progress to Electron UI in real-time
9. **HTML rewriting** makes saved page self-contained
10. **File saved** to downloads folder

## Resource Detection

### Frontend (preload script)
- Scans DOM for `<video>`, `<audio>`, `<img>`, `<a>` tags
- Intercepts `fetch()` and `XMLHttpRequest` in page context
- Sends detected URLs to backend via IPC

### Backend (browser.py)
- Playwright `page.route()` for network interception
- `response.json()` for API data extraction
- `__NEXT_DATA__` and `__APOLLO_STATE__` extraction for React/Apollo apps

## Security Notes

- **CORS** enabled for local development (`allow_origins=["*"]`)
- **Context isolation** enabled in Electron
- **No node integration** in renderer (safe preload bridge)
- **Sandbox** disabled for Playwright (required for some sites)

## Troubleshooting

### Common Issues

1. **WebSocket not connecting**
   - Check if Python backend is running on port 8000
   - Look at log window or `http://127.0.0.1:8000/api/logs`

2. **Downloads not starting**
   - Verify Playwright browsers are installed: `playwright install chromium`

3. **External login browser not opening**
   - Check Python logs for errors
   - Ensure display is available (not headless server)
