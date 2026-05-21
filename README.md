# Web Downloader (Hybrid Engine)

A sophisticated web resource downloader and scraper that combines the power of a Python backend with a modern Electron frontend.

---

## Key Features

- **Dual-Chromium Architecture**: Uses Electron for the UI and Playwright (Headless Chromium) for powerful network interception and scraping.
- **Real-time Updates**: WebSocket-driven progress tracking for all active downloads.
- **Deep Resource Extraction**: Intercepts JS, CSS, images, and XHR requests to capture the full state of a webpage.
- **Hybrid Control**: A Python-driven log window alongside a React-based main interface.
- **Smart Queueing**: Resource manager controls concurrent downloads to prevent overload.
- **Session Sync**: Support for external browser sessions to access authenticated content.

---

## Project Structure

```
python-version/
├── backend/
│   ├── main.py
│   ├── api.py
│   ├── browser.py
│   ├── downloader_queue.py
│   └── scraper.py
│
├── frontend/
│   ├── src/
│   └── package.json
│
├── ARCHITECTURE.md
├── start.py
└── requirements.txt
```

---

## Architecture

This project uses a hybrid bridge between Node.js and Python:

1. Frontend (Electron/React) handles the user interface and download queue.
2. Backend (FastAPI/Python) handles scraping and automation tasks.
3. Communication between them uses HTTP and WebSockets.

---

## Getting Started

### 1. Clone the repository

```
git clone https://github.com/abdelilah1223/L7rrata.git
cd L7rrata
```

### 2. Setup Python backend

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 3. Setup frontend

```
cd frontend
npm install
cd ..
```

### 4. Run the project

```
python start.py
```

---

## Roadmap

- Persistent storage using SQLite
- Advanced filtering for file types
- Parallel scraping improvements
- Production build packaging

---

## License

ISC
