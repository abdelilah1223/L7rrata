import logging
from collections import deque
import threading
import time

class MemoryLogger:
    def __init__(self, max_logs=500):
        self.logs = deque(maxlen=max_logs)
        self.lock = threading.Lock()

    def log(self, level, message):
        msg = f"{time.strftime('%H:%M:%S')} [{level}] {message}"
        with self.lock:
            self.logs.append(msg)
        print(msg) # Still print to terminal

    def info(self, msg): self.log("INFO", msg)
    def error(self, msg): self.log("ERROR", msg)
    def warn(self, msg): self.log("WARN", msg)

    def get_logs_html(self):
        with self.lock:
            log_lines = list(self.logs)
        
        lines_html = "".join([f"<div style='margin-bottom:6px; font-family:\"Consolas\", \"Monaco\", monospace; font-size:12px; border-bottom:1px solid #333; padding-bottom:4px; line-height:1.4;'>{line}</div>" for line in reversed(log_lines)])
        
        return f"""
        <html>
            <body style='background-color:#111; color:#0f0; margin:0; padding:15px; font-family:sans-serif; user-select: text !important; -webkit-user-select: text !important;'>
                <div style='display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #333; margin-bottom:15px; padding-bottom:10px;'>
                    <h3 style='color:#fff; margin:0; letter-spacing:1px;'>PYTHON ENGINE LOGS</h3>
                    <span style='color:#666; font-size:10px;'>Auto-refreshing...</span>
                </div>
                <div id='log-container' style='user-select: text !important;'>{lines_html}</div>
                <script>
                    setTimeout(() => window.location.reload(), 3000);
                </script>
            </body>
        </html>
        """

global_logger = MemoryLogger()
