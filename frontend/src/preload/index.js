const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
    // Settings
    getSettings: () => ipcRenderer.invoke('get-settings'),
    saveSettings: (settings) => ipcRenderer.send('save-settings', settings),
    getDownloads: () => ipcRenderer.invoke('get-downloads'),

    // Downloads
    startDownload: (url) => ipcRenderer.send('start-download', url),
    stopDownload: () => ipcRenderer.send('stop-download'),
    openFolder: (folderPath) => ipcRenderer.send('open-folder', folderPath),
    openFile: (data) => ipcRenderer.send('open-file', data),

    // Events
    onProgress: (callback) => {
        const subscription = (event, data) => callback(data);
        ipcRenderer.on('progress', subscription);
        return () => ipcRenderer.removeListener('progress', subscription);
    },
    onDetectedFile: (callback) => {
        const subscription = (event, data) => callback(data);
        ipcRenderer.on('detected-file', subscription);
        return () => ipcRenderer.removeListener('detected-file', subscription);
    },
    onDetectedFileBatch: (callback) => {
        const subscription = (event, data) => callback(data);
        ipcRenderer.on('detected-files-batch', subscription);
        return () => ipcRenderer.removeListener('detected-files-batch', subscription);
    },

    // Download Manager
    onDownloadUpdated: (callback) => {
        const subscription = (event, data) => callback(data);
        ipcRenderer.on('download-updated', subscription);
        return () => ipcRenderer.removeListener('download-updated', subscription);
    },
    onDownloadRemoved: (callback) => {
        const subscription = (event, id) => callback(id);
        ipcRenderer.on('download-removed', subscription);
        return () => ipcRenderer.removeListener('download-removed', subscription);
    },
    onDownloadsCleared: (callback) => {
        const subscription = (event) => callback();
        ipcRenderer.on('downloads-cleared', subscription);
        return () => ipcRenderer.removeListener('downloads-cleared', subscription);
    },
    sendDownloadControl: (data) => ipcRenderer.send('download-control', data),

    // Direct Download
    downloadFile: (file) => ipcRenderer.send('download-file', file),

    // Context Menu
    showContextMenu: (params) => ipcRenderer.send('webview-context-menu', params),
    onContextMenuCommand: (callback) => {
        const subscription = (event, command, params) => callback(command, params);
        ipcRenderer.on('context-menu-command', subscription);
        return () => ipcRenderer.removeListener('context-menu-command', subscription);
    },

    // Webview media from content scripts
    sendWebviewMedia: (items) => ipcRenderer.send('webview-media-detected', items),

    // External Browser Login
    openExternalLogin: (url) => ipcRenderer.send('open-external-login', url),
    onExternalLoginStatus: (callback) => {
        const subscription = (event, msg) => callback(msg);
        ipcRenderer.on('external-login-status', subscription);
        return () => ipcRenderer.removeListener('external-login-status', subscription);
    },
    onExternalLoginClosed: (callback) => {
        const subscription = (event) => callback();
        ipcRenderer.on('external-login-closed', subscription);
        return () => ipcRenderer.removeListener('external-login-closed', subscription);
    },
    onExternalLoginError: (callback) => {
        const subscription = (event, err) => callback(err);
        ipcRenderer.on('external-login-error', subscription);
        return () => ipcRenderer.removeListener('external-login-error', subscription);
    },
    onOpenNewTab: (callback) => {
        const subscription = (event, url) => callback(url);
        ipcRenderer.on('open-new-tab', subscription);
        return () => ipcRenderer.removeListener('open-new-tab', subscription);
    },
    onDeepDataReceived: (callback) => {
        const subscription = (event, data) => callback(data);
        ipcRenderer.on('deep-data-received', subscription);
        return () => ipcRenderer.removeListener('deep-data-received', subscription);
    },

    removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});

// ─── DOM MEDIA SCANNER (runs in main window context) ─────────────────────────
const seenResources = new Set();
let debounceTimer = null;

function normalizeResourceUrl(input) {
    if (!input || typeof input !== 'string') return input;
    try {
        const u = new URL(input);
        // Remove byte-range fragment params to avoid thousands of duplicate chunks.
        [
            'bytestart', 'byteend', 'range_start', 'range_end', 'start', 'end'
        ].forEach(k => u.searchParams.delete(k));
        return u.toString();
    } catch (e) {
        return input;
    }
}

function scanMedia() {
    const media = [];
    const extensions = {
        video: ['.mp4', '.webm', '.mkv', '.m3u8', '.m3u', '.ts', '.m2ts', '.mov', '.avi', '.mpd', '.m4s', '.flv', '.f4v', '.wmv', '.3gp'],
        audio: ['.mp3', '.wav', '.ogg', '.oga', '.opus', '.m4a', '.flac', '.aac', '.aiff', '.wma', '.amr'],
        image: ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tif', '.tiff', '.avif', '.heic', '.heif'],
        document: ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar', '.7z']
    };

    function add(src, type) {
        const normalized = normalizeResourceUrl(src);
        if (!normalized || seenResources.has(normalized)) return;
        if (!normalized.startsWith('http') && !normalized.startsWith('blob:')) return;
        seenResources.add(normalized);
        
        let name = 'file';
        try {
            if (!normalized.startsWith('blob:')) {
                const url = new URL(normalized);
                const parts = url.pathname.split('/').filter(Boolean);
                name = parts[parts.length - 1] || 'file';
                name = name.split('?')[0] || 'file';
            } else {
                name = 'blob-media';
            }
        } catch (e) {}

        media.push({ src: normalized, url: normalized, type, name });
    }

    // 1. Videos & Audios
    document.querySelectorAll('video, audio').forEach(el => {
        const type = el.tagName.toLowerCase() === 'video' ? 'video/mp4' : 'audio/mp3';
        add(el.src, type);
        el.querySelectorAll('source').forEach(s => add(s.src, s.type || type));
        if (el.poster) add(el.poster, 'image/jpeg');
    });

    // 2. Images (including lazy loads)
    document.querySelectorAll('img').forEach(img => {
        add(img.src, 'image/jpeg');
        add(img.getAttribute('data-src'), 'image/jpeg');
        add(img.getAttribute('data-original'), 'image/jpeg');
        add(img.getAttribute('data-lazy-src'), 'image/jpeg');
        if (img.srcset) {
            img.srcset.split(',').forEach(s => {
                const parts = s.trim().split(/\s+/);
                if (parts[0]) add(parts[0], 'image/jpeg');
            });
        }
    });

    // 3. Links (Deep Links / Assets)
    document.querySelectorAll('a').forEach(a => {
        const href = a.href;
        if (!href) return;
        const lowHref = href.toLowerCase().split('?')[0];
        
        if (extensions.video.some(ext => lowHref.endsWith(ext))) add(href, 'video/mp4');
        else if (extensions.audio.some(ext => lowHref.endsWith(ext))) add(href, 'audio/mp3');
        else if (extensions.image.some(ext => lowHref.endsWith(ext))) add(href, 'image/jpeg');
        else if (extensions.document.some(ext => lowHref.endsWith(ext))) add(href, 'application/octet-stream');
    });

    if (media.length > 0) {
        ipcRenderer.send('detected-files-batch', media);
    }
}

function debouncedScan() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(scanMedia, 1000);
}

// Run scan periodically
setInterval(debouncedScan, 5000);
window.addEventListener('click', () => debouncedScan());
window.addEventListener('scroll', () => debouncedScan());
window.addEventListener('load', () => debouncedScan());

// ─── Passive network detection without CDP/Chromium hooks ───────────────────
// This captures URLs seen via fetch/XHR in page JS context.
// It does not intercept raw request/response bodies; it only detects URLs + content-type.
(function installNetworkDetectors() {
    try {
        const queue = [];
        let flushTimer = null;
        const MAX_QUEUE = 120;

        const flush = () => {
            if (queue.length === 0) return;
            const batch = queue.splice(0, queue.length);
            ipcRenderer.send('detected-files-batch', batch);
        };

        const scheduleFlush = () => {
            if (flushTimer) return;
            flushTimer = setTimeout(() => {
                flushTimer = null;
                flush();
            }, 700);
        };

        const pushDetected = (rawUrl, contentType = '') => {
            const url = normalizeResourceUrl(rawUrl);
            if (!url || (!url.startsWith('http') && !url.startsWith('blob:'))) return;
            if (seenResources.has(url)) return;
            seenResources.add(url);

            let name = 'resource';
            try {
                if (!url.startsWith('blob:')) {
                    const u = new URL(url);
                    const p = u.pathname.split('/').filter(Boolean);
                    name = (p[p.length - 1] || 'resource').split('?')[0] || 'resource';
                }
            } catch (e) {}

            queue.push({
                src: url,
                url,
                type: contentType || 'application/octet-stream',
                name
            });

            if (queue.length >= MAX_QUEUE) {
                flush();
            } else {
                scheduleFlush();
            }
        };

        // fetch()
        if (typeof window.fetch === 'function') {
            const originalFetch = window.fetch.bind(window);
            window.fetch = async (...args) => {
                const response = await originalFetch(...args);
                try {
                    const reqUrl = typeof args[0] === 'string'
                        ? args[0]
                        : (args[0] && args[0].url) ? args[0].url : '';
                    const url = response && response.url ? response.url : reqUrl;
                    const ct = response && response.headers ? (response.headers.get('content-type') || '') : '';
                    pushDetected(url, ct);
                    // If this is a streaming manifest/segment-like response, classify clearly as media.
                    const lowCt = (ct || '').toLowerCase();
                    if (
                        lowCt.includes('mpegurl') ||
                        lowCt.includes('dash+xml') ||
                        lowCt.includes('video/') ||
                        lowCt.includes('audio/')
                    ) {
                        pushDetected(url, ct);
                    }
                } catch (e) {}
                return response;
            };
        }

        // XMLHttpRequest
        if (typeof XMLHttpRequest !== 'undefined') {
            const originalOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                this.__detected_url = url;
                return originalOpen.call(this, method, url, ...rest);
            };

            const originalSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.send = function(...args) {
                try {
                    this.addEventListener('loadend', function() {
                        try {
                            const ct = this.getResponseHeader('content-type') || '';
                            pushDetected(this.responseURL || this.__detected_url || '', ct);
                        } catch (e) {}
                    });
                } catch (e) {}
                return originalSend.apply(this, args);
            };
        }
    } catch (e) {
        // Keep preload resilient; ignore detector init failures.
    }
})();
