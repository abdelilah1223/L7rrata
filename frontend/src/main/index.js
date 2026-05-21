const { app, BrowserWindow, ipcMain, shell, protocol, net, session, Menu, MenuItem } = require('electron');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const WebSocket = require('ws');

// Register local protocol
protocol.registerSchemesAsPrivileged([
    {
        scheme: 'local',
        privileges: {
            standard: true,
            secure: true,
            supportFetchAPI: true,
            bypassCSP: true,
            stream: true
        }
    }
]);

let mainWindow;
let pythonProcess;
let ws;

const PYTHON_API = "http://127.0.0.1:8000/api";
const PYTHON_WS = "ws://127.0.0.1:8000/api/ws";

function connectWS() {
    console.log("Connecting to Python WebSocket...");
    ws = new WebSocket(PYTHON_WS);
    
    ws.on('open', () => {
        console.log("Connected to Python engine via WebSocket.");
    });

    ws.on('message', (data) => {
        try {
            const msg = JSON.parse(data);
            if (mainWindow && !mainWindow.isDestroyed()) {
                if (msg.type === 'progress') {
                    mainWindow.webContents.send('download-updated', msg.data);
                } else if (msg.type === 'completed') {
                    mainWindow.webContents.send('download-updated', { ...msg.data, state: 'completed' });
                } else if (msg.type === 'error') {
                     mainWindow.webContents.send('download-updated', { id: msg.id, state: 'error', error: msg.error });
                } else if (msg.type === 'deep_data') {
                    mainWindow.webContents.send('deep-data-received', msg);
                }
            }
        } catch (e) {
            console.error("WS Message Error:", e);
        }
    });

    ws.on('error', (err) => {
        // Ignore errors, will retry
    });

    ws.on('close', () => {
        console.log("Python WebSocket closed. Retrying in 2s...");
        setTimeout(connectWS, 2000);
    });
}

function spawnPython() {
    console.log("Spawning Python backend...");
    const pythonExe = process.platform === 'win32' ? 'python' : 'python3';
    // Updated path to point correctly to the backend script
    const scriptPath = path.join(__dirname, '../../../backend/main.py');
    
    pythonProcess = spawn(pythonExe, [scriptPath], {
        env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });

    pythonProcess.stdout.on('data', (data) => {
        const str = data.toString();
        console.log(`[Python] ${str}`);
        // Optionally send logs to renderer
        if (mainWindow && !mainWindow.isDestroyed()) {
             mainWindow.webContents.send('python-log', str);
        }
    });
    pythonProcess.stderr.on('data', (data) => console.error(`[Python Error] ${data}`));
    
    // Connect WebSocket after a short delay
    setTimeout(connectWS, 3000);
}

// IPC Bridging
ipcMain.handle("get-settings", async () => {
    try {
        const res = await net.fetch(`${PYTHON_API}/settings`);
        if (res.ok) {
            const settings = await res.json();
            // Inject absolute preload path for webviews
            settings.webviewPreloadPath = path.join(__dirname, '../preload/index.js');
            return settings;
        }
    } catch (e) {}
    return { 
        proxy: { enabled: false },
        webviewPreloadPath: path.join(__dirname, '../preload/index.js')
    };
});

ipcMain.on("save-settings", async (e, settings) => {
    try {
        await net.fetch(`${PYTHON_API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
    } catch (e) {}
});

ipcMain.handle("get-downloads", async () => {
    try {
        const res = await net.fetch(`${PYTHON_API}/downloads`);
        if (res.ok) return await res.json();
    } catch (e) {}
    return [];
});

ipcMain.on('download-control', async (event, { action, id }) => {
    try {
        let url = `${PYTHON_API}/downloads/${id}`;
        let method = 'POST';
        if (action === 'remove' || action === 'delete-file') {
            method = 'DELETE';
            url = `${PYTHON_API}/downloads/${id}/delete`;
        } else if (action === 'open') {
            url = `${PYTHON_API}/downloads/${id}/open`;
        } else if (action === 'pause' || action === 'resume' || action === 'cancel') {
             // Basic placeholder if implemented in python later
             return;
        } else {
             return;
        }
        await net.fetch(url, { method });
    } catch (e) {}
});

ipcMain.on("download-file", (e, payload) => {
    const files = Array.isArray(payload) ? payload : (payload.files || [payload]);
    files.forEach(file => {
        const url = file.url || file.src;
        if (!url || url.startsWith('blob:')) return;
        net.fetch(`${PYTHON_API}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, content_type: file.type || '' })
        }).catch(err => console.error("Python Download Error:", err));
    });
});

ipcMain.on('webview-media-detected', (e, items) => {
    console.log(`[IPC] webview-media-detected: ${items.length} items`);
    if (!Array.isArray(items)) return;
    items.forEach(item => {
        const url = item.url || item.src;
        if (!url || url.startsWith('blob:')) return;
        net.fetch(`${PYTHON_API}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, content_type: item.type || '' })
        }).catch(err => console.error("Python Download Error:", err));
    });
});

ipcMain.on('detected-files-batch', (e, files) => {
    console.log(`[IPC] detected-files-batch: ${files.length} items`);
    if (!Array.isArray(files)) return;
    files.forEach(file => {
        const url = file.url || file.src;
        if (!url || url.startsWith('blob:')) return;
        net.fetch(`${PYTHON_API}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, content_type: file.type || '' })
        }).catch(err => console.error("Python Batch Download Error:", err));
    });
});

// External Login via Python API (uses Playwright instead of local Puppeteer)
ipcMain.on('open-external-login', async (event, currentUrl) => {
    try {
        // Start external login browser via Python API
        const res = await net.fetch(`${PYTHON_API}/external-login/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: currentUrl })
        });
        
        if (!res.ok) {
            throw new Error(`API error: ${res.status}`);
        }
        
        const result = await res.json();
        
        if (result.status === 'opened') {
            event.sender.send('external-login-status', 'Opened external browser. Cookies will auto-sync.');
            
            // Start cookie sync interval
            const syncInterval = setInterval(async () => {
                try {
                    const syncRes = await net.fetch(`${PYTHON_API}/external-login/sync-cookies`, {
                        method: 'POST'
                    });
                    
                    if (syncRes.ok) {
                        const syncData = await syncRes.json();
                        
                        // Apply cookies to Electron's session
                        if (syncData.cookies && syncData.cookies.length > 0) {
                            for (const c of syncData.cookies) {
                                let domain = c.domain;
                                let urlDomain = domain.startsWith('.') ? domain.substring(1) : domain;
                                const url = (c.secure ? 'https://' : 'http://') + urlDomain + c.path;
                                let sameSite = 'unspecified';
                                if (c.sameSite === 'Strict') sameSite = 'strict';
                                else if (c.sameSite === 'Lax') sameSite = 'lax';
                                else if (c.sameSite === 'None') sameSite = 'no_restriction';
                                
                                await session.defaultSession.cookies.set({
                                    url: url,
                                    name: c.name,
                                    value: c.value,
                                    path: c.path,
                                    secure: c.secure,
                                    httpOnly: c.httpOnly,
                                    sameSite: sameSite,
                                    domain: domain.startsWith('.') ? domain : undefined,
                                    expirationDate: c.expires && c.expires > 0 ? c.expires : undefined
                                });
                            }
                        }
                    }
                    
                    // Check if browser still running
                    const statusRes = await net.fetch(`${PYTHON_API}/external-login/status`);
                    if (statusRes.ok) {
                        const status = await statusRes.json();
                        if (!status.running) {
                            clearInterval(syncInterval);
                            if (!event.sender.isDestroyed()) {
                                event.sender.send('external-login-closed');
                            }
                        }
                    }
                } catch (err) {
                    // Silently ignore sync errors
                }
            }, 3000);
            
        } else {
            throw new Error(result.message || 'Failed to open external login');
        }
        
    } catch (err) {
        console.error('[ExternalLogin] Error:', err.message);
        if (!event.sender.isDestroyed()) {
            event.sender.send('external-login-error', err.message);
        }
    }
});

function createWindow() {
    // spawnPython(); // Redundant with start.py

    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        backgroundColor: '#030712', // Match gray-950
        titleBarStyle: 'hidden',
        titleBarOverlay: {
            color: '#111827', // Gray-900
            symbolColor: '#94a3b8', // Gray-400
            height: 35
        },
        webPreferences: {
            preload: path.join(__dirname, '../preload/index.js'),
            webviewTag: true,
            contextIsolation: true,
            nodeIntegration: false
        }
    });

    if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
        mainWindow.loadURL('http://localhost:5173');
    } else {
        mainWindow.loadFile(path.join(__dirname, '../../dist/renderer/index.html'));
    }

    // Global fail-safe to prevent any new windows from being opened
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        console.log("[Main] Window open blocked by handler:", url);
        return { action: 'deny' };
    });
}
app.whenReady().then(() => {
    createWindow();

    // Global Network Interception to capture all web resources
    session.defaultSession.webRequest.onCompleted({ urls: ['<all_urls>'] }, (details) => {
        // Skip mainframes (handled by Playwright) and devtools
        if (details.resourceType === 'mainFrame' || details.resourceType === 'subFrame' || details.url.startsWith('devtools://')) return;
        
        // Skip local queries to avoid infinite loops
        if (details.url.includes('127.0.0.1') || details.url.includes('localhost')) return;

        let contentType = '';
        if (details.responseHeaders) {
            const ctHeaderKey = Object.keys(details.responseHeaders).find(k => k.toLowerCase() === 'content-type');
            if (ctHeaderKey) {
                contentType = details.responseHeaders[ctHeaderKey][0];
            }
        }

        // Send resource URL to Python backend for extraction and queuing
        net.fetch(`${PYTHON_API}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: details.url, content_type: contentType })
        }).catch(err => {
            // Silently ignore if backend is busy or restarting
        });
    });
});

// Global fail-safe: Ensure EVERY webContents (including webviews) blocks new windows
app.on('web-contents-created', (event, contents) => {
    contents.setWindowOpenHandler(({ url }) => {
        console.log("[Global] Window open blocked by handler:", url);
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('open-new-tab', url);
        }
        return { action: 'deny' };
    });
});

app.on('window-all-closed', () => {
    if (pythonProcess) pythonProcess.kill();
    if (process.platform !== 'darwin') app.quit();
});
