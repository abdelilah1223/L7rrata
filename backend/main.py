import os
import sys
import threading
import time
import uvicorn
import webview
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Add the current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api import router as api_router

app = FastAPI(title="Web Downloader API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")

# Serve frontend if built (during production)
frontend_dist = os.path.abspath("../frontend/dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

from logger import global_logger
from fastapi.responses import HTMLResponse
import webview
import webbrowser
import os

@app.get("/api/logs", response_class=HTMLResponse)
async def get_logs():
    return global_logger.get_logs_html()

def start_fastapi():
    uvicorn.run(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    # Start FastAPI in a separate thread
    t = threading.Thread(target=start_fastapi, daemon=True)
    t.start()
    
    # Give FastAPI a moment to start
    time.sleep(2)

    # Main UI is managed by Electron, so we only open the Log Screen here
    
    # Open the Log Screen in a standalone pywebview window
    print("Launching Python Log Screen...")
    try:
        window = webview.create_window(
            "Python Engine Logs",
            "http://127.0.0.1:8000/api/logs",
            width=600,
            height=500,
            resizable=True,
            on_top=True
        )
        webview.start()
    except Exception as e:
        print(f"Could not start Log Window: {e}. Logs are available at http://127.0.0.1:8000/api/logs")
        # Fallback to keeping thread alive if webview fails
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
