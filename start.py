import subprocess
import os
import sys
import time

if __name__ == "__main__":
    # Ensure current dir is python-version
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    def kill_port(port):
        try:
            if sys.platform == "win32":
                output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
                for line in output.strip().split("\n"):
                    parts = line.split()
                    if len(parts) > 4 and f":{port}" in parts[1]:
                        pid = parts[-1]
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            else:
                subprocess.run(f"lsof -ti:{port} | xargs kill -9", shell=True, capture_output=True)
        except Exception:
            pass

    print("--- WEB DOWNLOADER HYBRID STARTUP ---")
    kill_port(5173)
    kill_port(8000)
    
    # 1. Start Vite in background (from frontend folder)
    print("Step 1: Starting Vite Dev Server...")
    p_vite = subprocess.Popen("npm run vite", cwd=os.path.join(base_dir, "frontend"), shell=True)
    
    # 2. Start Backend (from backend folder)
    print("Step 2: Starting Backend Server...")
    python_exe = f'"{sys.executable}"'
    p_backend = subprocess.Popen(f"{python_exe} main.py", cwd=os.path.join(base_dir, "backend"), shell=True)
    
    # 3. Start Electron (from frontend folder)
    print("Step 3: Launching Electron UI...")
    # Give Vite/Backend a moment to initialize ports
    time.sleep(5)
    p_electron = subprocess.Popen("npm run electron", cwd=os.path.join(base_dir, "frontend"), shell=True)
    
    print("\n--- HYBRID SYSTEM STARTED ---")
    print("Main UI: Electron Window")
    print("Logs: Standalone Python Screen")

    try:
        # Keep the script running to manage child processes
        while True:
            time.sleep(2)
            if p_vite.poll() is not None:
                print("Vite process ended.")
                break
            if p_backend.poll() is not None:
                print("Backend process ended.")
                break
            if p_electron.poll() is not None:
                print("Electron process ended.")
                break
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        print("Cleaning up...")
        if p_vite.poll() is None: p_vite.terminate()
        if p_backend.poll() is None: p_backend.terminate()
        if p_electron.poll() is None: p_electron.terminate()
        print("Done.")
