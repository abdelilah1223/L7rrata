import React, { useState, useRef, useEffect } from 'react';
import { Search, Globe, ArrowLeft, ArrowRight, RotateCw, X, Download, List, Plus, Settings, FolderOpen, Shield, Database, Code, Info } from 'lucide-react';

// Content script and manual injection removed - now handled by preload/index.js

export default function MainTab() {
    // Tabs State: [{ id, url, title, isLoading, canGoBack, canGoForward }]
    const [tabs, setTabs] = useState([{ id: 1, url: 'https://abdelilah.wuaze.com/', title: 'New Tab', isLoading: false, canGoBack: false, canGoForward: false }]);
    const [activeTabId, setActiveTabId] = useState(1);

    const [inputUrl, setInputUrl] = useState('');
    const [searchEngine, setSearchEngine] = useState('google');
    const [detectedResources, setDetectedResources] = useState([]);
    const [selectedResources, setSelectedResources] = useState(new Set()); // For multi-select
    const [showResourceModal, setShowResourceModal] = useState(false);
    const [filterType, setFilterType] = useState('all'); // all, image, video, audio, document, other

    const [autoDownload, setAutoDownload] = useState(true);
    const [externalLoginStatus, setExternalLoginStatus] = useState(null);
    const [deepData, setDeepData] = useState([]);
    const [showDataModal, setShowDataModal] = useState(false);
    const [selectedData, setSelectedData] = useState(null); // For viewing a specific JSON object

    const isHomePage = (url) => {
        if (!url) return false;
        const normalize = (u) => u.replace(/\/$/, '').toLowerCase();
        return normalize(url) === normalize('https://abdelilah.wuaze.com');
    };

    // Refs for webviews (map of id -> ref)
    const webviewRefs = useRef({});
    const activeTabIdRef = useRef(activeTabId);
    const lastSyncedUrlRef = useRef({}); // tabId -> lastUrl

    // Sync input with active tab URL when switching tabs
    useEffect(() => {
        const activeTab = tabs.find(t => t.id === activeTabId);
        if (activeTab) {
            setInputUrl(isHomePage(activeTab.url) ? '' : activeTab.url);
        }
        activeTabIdRef.current = activeTabId;
    }, [activeTabId, tabs]);

    const [webviewPreloadPath, setWebviewPreloadPath] = useState(null);

    useEffect(() => {
        window.api.getSettings().then(s => {
            setAutoDownload(s.autoDownload);
            if (s.webviewPreloadPath) setWebviewPreloadPath(s.webviewPreloadPath);
        });

        // Listen for detected files (Batched or Single)
        const handleDetectedFile = (data) => {
            const files = Array.isArray(data) ? data : [data];

            setDetectedResources(prev => {
                // Deduplicate by URL
                const existingUrls = new Set(prev.map(p => p.url || p.src));
                const newFiles = files
                    .map(f => ({ ...f, url: f.url || f.src }))
                    .filter(f => f.url && !existingUrls.has(f.url));

                if (newFiles.length === 0) return prev;
                const updated = [...prev, ...newFiles];
                if (updated.length > 200) {
                    return updated.slice(-200);
                }
                return updated;
            });
        };

        const removeSingleListener = window.api.onDetectedFile(handleDetectedFile);
        let removeBatchListener = () => { };
        if (window.api.onDetectedFileBatch) {
            removeBatchListener = window.api.onDetectedFileBatch(handleDetectedFile);
        }

        // Handle Context Menu Commands
        const cleanupMenu = window.api.onContextMenuCommand((command, params) => {
            const currentWebview = webviewRefs.current[activeTabIdRef.current];
            if (!currentWebview) return;

            if (command === 'inspect') {
                currentWebview.inspectElement(params.x, params.y);
            } else if (command === 'new-tab') {
                const newId = Date.now();
                const newTab = { id: newId, url: params, title: 'New Tab', isLoading: true, canGoBack: false, canGoForward: false };
                setTabs(prev => [...prev, newTab]);
                setActiveTabId(newId);
            } else if (command === 'copy-image') {
                currentWebview.copyImageAt(params.x, params.y);
            }
        });

        // External Login Events
        const removeExtStatus = window.api.onExternalLoginStatus((msg) => {
            setExternalLoginStatus(msg);
        });
        const removeExtClosed = window.api.onExternalLoginClosed(() => {
            setExternalLoginStatus(null);
            const currentWebview = webviewRefs.current[activeTabIdRef.current];
            if (currentWebview) currentWebview.reload();
        });
        const removeExtError = window.api.onExternalLoginError((err) => {
            setExternalLoginStatus(`Error: ${err}`);
            setTimeout(() => setExternalLoginStatus(null), 3500);
        });

        // Handle global new tab requests (from main process)
        const removeNewTabListener = window.api.onOpenNewTab((url) => {
            console.log("[Renderer] Received global new tab request:", url);
            const newId = Date.now();
            const newTab = { id: newId, url, title: 'New Tab', isLoading: true, canGoBack: false, canGoForward: false };
            setTabs(prev => [...prev, newTab]);
            setActiveTabId(newId);
        });

        // Handle Deep Data (JSON/GraphQL)
        const removeDeepDataListener = window.api.onDeepDataReceived((msg) => {
            setDeepData(prev => {
                // Keep only unique URLs to avoid spam, but update if response changes?
                // For now, just add to the top and limit to 100 items.
                const newItem = {
                    id: Date.now() + Math.random(),
                    ...msg.data,
                    timestamp: new Date().toLocaleTimeString()
                };
                return [newItem, ...prev].slice(0, 100);
            });
        });

        return () => {
            removeSingleListener();
            removeBatchListener();
            cleanupMenu();
            removeExtStatus();
            removeExtClosed();
            removeExtError();
            removeNewTabListener();
            removeDeepDataListener();
        };
    }, []);

    // Tab Management
    const addTab = () => {
        const newId = Date.now();
        const newTab = { id: newId, url: 'https://abdelilah.wuaze.com/', title: 'New Tab', isLoading: false, canGoBack: false, canGoForward: false };
        setTabs([...tabs, newTab]);
        setActiveTabId(newId);
    };

    const closeTab = (e, id) => {
        e.stopPropagation();
        if (tabs.length === 1) return; // Don't close last tab
        const newTabs = tabs.filter(t => t.id !== id);
        setTabs(newTabs);
        if (activeTabId === id) {
            setActiveTabId(newTabs[newTabs.length - 1].id);
        }
        delete webviewRefs.current[id];
    };

    const updateTab = (id, updates) => {
        setTabs(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t));
    };

    // Navigation Logic
    const handleNavigate = () => {
        let target = inputUrl.trim();
        const isUrl = (string) => {
            try { return Boolean(new URL(string)); }
            catch (e) { return false; }
        }

        const hasDomain = (string) => {
            return string.includes('.') && !string.includes(' ');
        }

        if (!target.startsWith('http://') && !target.startsWith('https://')) {
            if (hasDomain(target)) {
                target = 'https://' + target;
            } else {
                if (searchEngine === 'google') {
                    target = `https://www.google.com/search?q=${encodeURIComponent(target)}`;
                } else {
                    target = `https://yandex.com/search/?text=${encodeURIComponent(target)}`;
                }
            }
        }

        updateTab(activeTabId, { url: target });
        const webview = webviewRefs.current[activeTabId];
        if (webview) {
            webview.loadURL(target);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') handleNavigate();
    };

    const getActiveWebview = () => webviewRefs.current[activeTabId];

    const reload = () => getActiveWebview()?.reload();
    const goBack = () => getActiveWebview()?.goBack();
    const goForward = () => getActiveWebview()?.goForward();
    const stop = () => getActiveWebview()?.stop();
    const openDevTools = () => getActiveWebview()?.openDevTools();

    const openDownloadsFolder = () => {
        window.api.openFolder();
    };

    const handleExternalLogin = () => {
        const activeTab = tabs.find(t => t.id === activeTabId);
        if (activeTab && activeTab.url) {
            setExternalLoginStatus('Starting external browser...');
            window.api.openExternalLogin(activeTab.url);
        }
    };

    // injectContentScript moved to preload logic

    // Webview Event Handlers (Factory)
    const setupWebview = (id, webview) => {
        if (!webview) return;
        webviewRefs.current[id] = webview;

        const onDidStartLoading = () => updateTab(id, { isLoading: true });
        const onDidStopLoading = () => {
            updateTab(id, { isLoading: false, canGoBack: webview.canGoBack(), canGoForward: webview.canGoForward() });
        };
        const onDidNavigate = (e) => {
            updateTab(id, { url: e.url, title: webview.getTitle() });
            if (id === activeTabIdRef.current) {
                setInputUrl(isHomePage(e.url) ? '' : e.url);
            }
            
            // SYNC: Notify Python only if URL actually changed
            if (lastSyncedUrlRef.current[id] !== e.url) {
                lastSyncedUrlRef.current[id] = e.url;
                fetch('http://127.0.0.1:8000/api/browser', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command: 'navigate', url: e.url, tab_id: String(id) })
                }).catch(err => console.error("Sync Error:", err));
            }
        };
        const onDidFailLoad = (e) => {
            updateTab(id, { isLoading: false, canGoBack: webview.canGoBack(), canGoForward: webview.canGoForward() });
        };
        const onPageTitleUpdated = (e) => updateTab(id, { title: e.title });
        const onNewWindow = (e) => {
            // Prevent Electron from opening a new window
            e.preventDefault();
            const url = e.url || (e.options && e.options.url);
            console.log("[Webview] New window requested:", url);
            
            if (url && url.startsWith('http')) {
                const newId = Date.now();
                const newTab = { id: newId, url: url, title: 'New Tab', isLoading: true, canGoBack: false, canGoForward: false };
                setTabs(prev => [...prev, newTab]);
                setActiveTabId(newId);
            }
        };
        const onContextMenu = (e) => {
            window.api.showContextMenu(e.params);
        };

        webview.addEventListener('did-start-loading', onDidStartLoading);
        webview.addEventListener('did-stop-loading', onDidStopLoading);
        webview.addEventListener('did-fail-load', onDidFailLoad);
        webview.addEventListener('did-navigate', onDidNavigate);
        webview.addEventListener('page-title-updated', onPageTitleUpdated);
        webview.addEventListener('new-window', onNewWindow);
        webview.addEventListener('did-create-window', onNewWindow); // Backup for modern Electron
        webview.addEventListener('context-menu', onContextMenu);
    };

    // Selection Logic
    const getFilteredResources = () => {
        if (filterType === 'all') return detectedResources;
        return detectedResources.filter(r => {
            const type = r.type || '';
            if (filterType === 'image') return type.startsWith('image/');
            if (filterType === 'video') return type.startsWith('video/') || type.includes('mpegurl') || type.includes('dash');
            if (filterType === 'audio') return type.startsWith('audio/');
            if (filterType === 'document') return type.includes('pdf') || type.includes('text') || type.includes('json') || type.includes('xml');
            return !type.startsWith('image/') && !type.startsWith('video/') && !type.startsWith('audio/');
        });
    };

    const filteredResources = getFilteredResources();
    const toggleSelection = (url) => {
        const newSet = new Set(selectedResources);
        if (newSet.has(url)) newSet.delete(url);
        else newSet.add(url);
        setSelectedResources(newSet);
    }

    const toggleAll = () => {
        const visible = filteredResources;
        const allSelected = visible.length > 0 && visible.every(r => selectedResources.has(r.url));

        const newSet = new Set(selectedResources);
        if (allSelected) {
            visible.forEach(r => newSet.delete(r.url));
        } else {
            visible.forEach(r => newSet.add(r.url));
        }
        setSelectedResources(newSet);
    }

    const downloadSelected = () => {
        const filesToDownload = detectedResources.filter(r => selectedResources.has(r.url));
        if (filesToDownload.length === 0) return;

        const isBatch = filesToDownload.length > 1;
        window.api.downloadFile({ files: filesToDownload, isBatch });
        setSelectedResources(new Set());
        setShowResourceModal(false);
    }

    const renderThumbnail = (file) => {
        const type = file.type || '';
        if (type.startsWith('image/')) {
            return <img src={file.url} className="w-full h-full object-cover rounded" alt="" />;
        }
        const icon = type.startsWith('video/') || type.includes('mpegurl') ? '▶' :
                     type.startsWith('audio/') ? '♪' : '📄';
        return (
            <div className="w-full h-full bg-gray-700 flex items-center justify-center text-base">
                {icon}
            </div>
        );
    };

    const getTypeIcon = (type) => {
        if (!type) return '📄';
        if (type.startsWith('image/')) return '🖼️';
        if (type.startsWith('video/') || type.includes('mpegurl') || type.includes('dash')) return '🎬';
        if (type.startsWith('audio/')) return '🎵';
        if (type.includes('blob')) return '🔵';
        return '📄';
    };

    return (
        <div className="flex flex-col h-full bg-gray-950 text-white relative">
            {/* Tabs Bar */}
            <div 
                className="flex items-center bg-gray-900 border-b border-gray-800 px-2 pt-2 gap-1 overflow-x-hidden custom-scrollbar"
                style={{ WebkitAppRegion: 'drag' }}
            >
                {tabs.map(tab => (
                    <div
                        key={tab.id}
                        onClick={() => setActiveTabId(tab.id)}
                        className={`group relative flex items-center min-w-[150px] max-w-[200px] h-9 px-3 rounded-t-lg cursor-pointer text-xs select-none transition-colors ${activeTabId === tab.id ? 'bg-gray-800 text-white' : 'bg-gray-950/50 text-gray-400 hover:bg-gray-800/80 hover:text-gray-200'
                            }`}
                        style={{ WebkitAppRegion: 'no-drag' }}
                    >
                        {tab.isLoading && <RotateCw size={12} className="animate-spin mr-2 text-blue-400" />}
                        {!tab.isLoading && <Globe size={12} className="mr-2 opacity-70" />}
                        <span className="truncate flex-1">{tab.title || 'New Tab'}</span>
                        <button
                            onClick={(e) => closeTab(e, tab.id)}
                            className={`ml-2 p-0.5 rounded-md hover:bg-gray-700 opacity-0 group-hover:opacity-100 transition-opacity ${tabs.length === 1 ? 'hidden' : ''}`}
                        >
                            <X size={12} />
                        </button>
                    </div>
                ))}
                <button onClick={addTab} className="p-2 hover:bg-gray-800 rounded-lg text-gray-400 transition-colors" style={{ WebkitAppRegion: 'no-drag' }}>
                    <Plus size={16} />
                </button>
                <div className="flex-1 min-w-[20px]" style={{ WebkitAppRegion: 'drag' }}></div>
                <div className="w-[140px] shrink-0 h-full" style={{ WebkitAppRegion: 'drag' }}></div>
            </div>

            {/* Navigation Bar */}
            <div className="h-14 flex items-center px-4 border-b border-gray-800 bg-gray-900/50 backdrop-blur gap-3">
                <div className="flex items-center gap-1">
                    <button onClick={goBack} disabled={!tabs.find(t => t.id === activeTabId)?.canGoBack} className="p-2 disabled:opacity-30 hover:bg-gray-800 rounded-lg text-gray-400 transition-colors">
                        <ArrowLeft size={16} />
                    </button>
                    <button onClick={goForward} disabled={!tabs.find(t => t.id === activeTabId)?.canGoForward} className="p-2 disabled:opacity-30 hover:bg-gray-800 rounded-lg text-gray-400 transition-colors">
                        <ArrowRight size={16} />
                    </button>
                    <button onClick={reload} className="p-2 hover:bg-gray-800 rounded-lg text-gray-400 transition-colors">
                        {tabs.find(t => t.id === activeTabId)?.isLoading ? <X size={16} onClick={stop} /> : <RotateCw size={16} />}
                    </button>
                </div>

                <div className="flex-1 flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-1.5 border border-gray-700 focus-within:border-blue-500 transition-all">
                    {searchEngine === 'google' ? (
                        <Globe size={14} className="text-blue-400 cursor-pointer" onClick={() => setSearchEngine('yandex')} title="Switch to Yandex" />
                    ) : (
                        <span className="text-red-500 font-bold text-[10px] cursor-pointer" onClick={() => setSearchEngine('google')} title="Switch to Google">Y</span>
                    )}
                    <input
                        type="text"
                        value={inputUrl}
                        onChange={(e) => setInputUrl(e.target.value)}
                        onKeyDown={handleKeyDown}
                        className="flex-1 bg-transparent border-none text-white focus:outline-none text-sm"
                        placeholder="Search or enter URL..."
                        onFocus={(e) => e.target.select()}
                    />
                </div>

                {/* External Login Button */}
                <button
                    onClick={handleExternalLogin}
                    className="p-2 hover:bg-gray-800 rounded-lg text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
                    title="Login using real browser (Bypasses bot protections)"
                >
                    <Shield size={16} />
                </button>

                {/* Open Downloads Folder Button */}
                <button
                    onClick={openDownloadsFolder}
                    className="p-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-emerald-400 transition-colors"
                    title="Open Downloads Folder"
                >
                    <FolderOpen size={16} />
                </button>

                <button onClick={openDevTools} className="p-2 hover:bg-gray-800 rounded-lg text-gray-400 transition-colors" title="Developer Tools">
                    <Settings size={16} />
                </button>

                {/* Deep Data Button */}
                <button 
                  onClick={() => setShowDataModal(true)} 
                  className={`p-2 rounded-lg transition-colors relative ${deepData.length > 0 ? 'text-blue-400 hover:bg-blue-900/30' : 'text-gray-600'}`}
                  title="Deep Analysis (Captured JSON/GraphQL)"
                >
                  <Database size={16} />
                  {deepData.length > 0 && (
                    <span className="absolute top-1 right-1 w-2 h-2 bg-blue-500 rounded-full animate-pulse"></span>
                  )}
                </button>
            </div>

            {/* Loading Bar */}
            {tabs.find(t => t.id === activeTabId)?.isLoading && (
                <div className="h-0.5 w-full bg-gray-800 absolute top-[92px] z-10">
                    <div className="h-full bg-blue-500 animate-loading-bar"></div>
                </div>
            )}

            {/* External Login Status Banner */}
            {externalLoginStatus && (
                <div className="absolute top-[92px] left-1/2 -translate-x-1/2 z-20 mt-2 px-4 py-2 bg-blue-900 border border-blue-500 text-blue-100 rounded shadow-lg text-sm flex items-center gap-2">
                    <RotateCw className="animate-spin" size={14} />
                    {externalLoginStatus}
                </div>
            )}

            {/* Webviews Container */}
            <div className="flex-1 relative bg-white">
                {tabs.map(tab => (
                    <div
                        key={tab.id}
                        style={{ display: activeTabId === tab.id ? 'block' : 'none', height: '100%', width: '100%' }}
                    >
                        <webview
                            ref={(el) => setupWebview(tab.id, el)}
                            src={tab.url}
                            className="w-full h-full"
                            preload={webviewPreloadPath}
                            webpreferences="contextIsolation=yes,nodeIntegration=no,sandbox=no"
                            allowpopups="true"
                        ></webview>
                    </div>
                ))}
            </div>

            {/* FAB for Downloads */}
            {detectedResources.length > 0 && (
                <button
                    onClick={() => setShowResourceModal(true)}
                    className="absolute bottom-6 right-6 w-14 h-14 bg-blue-600 hover:bg-blue-500 rounded-full shadow-lg shadow-blue-600/30 flex items-center justify-center transition-transform hover:scale-105 z-20 group"
                    title="Detected Resources"
                >
                    <Download size={24} />
                    <span className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 rounded-full text-xs flex items-center justify-center font-bold border-2 border-gray-900">
                        {detectedResources.length > 99 ? '99+' : detectedResources.length}
                    </span>
                </button>
            )}

            {/* Resources Modal */}
            {showResourceModal && (
                <div className="absolute inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8 z-50">
                    <div className="bg-gray-900 w-full max-w-2xl max-h-[80vh] rounded-2xl border border-gray-800 flex flex-col shadow-2xl animate-in fade-in zoom-in duration-200 overflow-hidden">
                        <div className="p-6 border-b border-gray-800 flex justify-between items-center bg-gray-900/50">
                            <h2 className="text-xl font-bold flex items-center gap-2">
                                <List size={20} className="text-blue-400" />
                                Detected Resources
                                <span className="text-sm font-normal text-gray-400">({detectedResources.length} total)</span>
                            </h2>
                            <button onClick={() => setShowResourceModal(false)} className="text-gray-400 hover:text-white transition-colors">
                                <X size={24} />
                            </button>
                        </div>

                        {/* Toolbar */}
                        <div className="px-6 py-3 border-b border-gray-800 flex flex-col gap-3 bg-gray-900/30">
                            {/* Filter Buttons */}
                            <div className="flex gap-2 text-xs overflow-x-auto custom-scrollbar pb-1">
                                {['all', 'image', 'video', 'audio', 'document', 'other'].map(type => (
                                    <button
                                        key={type}
                                        onClick={() => setFilterType(type)}
                                        className={`px-3 py-1.5 rounded-full capitalize transition-colors whitespace-nowrap ${filterType === type ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                                            }`}
                                    >
                                        {type}
                                    </button>
                                ))}
                            </div>

                            <div className="flex items-center gap-4">
                                <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer select-none">
                                    <input
                                        type="checkbox"
                                        checked={filteredResources.length > 0 && filteredResources.every(r => selectedResources.has(r.url))}
                                        onChange={toggleAll}
                                        className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-offset-gray-900"
                                    />
                                    Select All ({filteredResources.length})
                                </label>
                                <span className="text-sm text-gray-500">{selectedResources.size} selected</span>
                                <button
                                    onClick={() => openDownloadsFolder()}
                                    className="ml-auto flex items-center gap-1.5 text-xs text-gray-400 hover:text-emerald-400 transition-colors"
                                    title="Open downloads folder"
                                >
                                    <FolderOpen size={14} />
                                    Open Folder
                                </button>
                            </div>

                        </div>

                        <div className="flex-1 overflow-y-auto min-h-0 p-2 custom-scrollbar space-y-1.5">
                            {filteredResources.length === 0 && (
                                <div className="text-center text-gray-500 py-12">No resources detected yet.</div>
                            )}
                            {filteredResources.map((file, idx) => (
                                <div
                                    key={idx}
                                    className={`p-3 rounded-lg flex items-center gap-3 transition-colors cursor-pointer ${selectedResources.has(file.url) ? 'bg-blue-900/20 border border-blue-500/30' : 'bg-gray-800 border border-transparent hover:bg-gray-700'
                                        }`}
                                    onClick={() => toggleSelection(file.url)}
                                >
                                    <input
                                        type="checkbox"
                                        checked={selectedResources.has(file.url)}
                                        readOnly
                                        className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-offset-gray-900 pointer-events-none"
                                    />
                                    <div className="w-8 h-8 shrink-0 rounded overflow-hidden">
                                        {renderThumbnail(file)}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm font-medium text-white truncate flex items-center gap-1.5">
                                            <span>{getTypeIcon(file.type)}</span>
                                            {file.name || 'media'}
                                            {file.isBlob && <span className="text-[10px] bg-purple-800/50 text-purple-300 px-1.5 py-0.5 rounded-full border border-purple-700/40 ml-1">blob</span>}
                                        </p>
                                        <p className="text-xs text-gray-500 truncate">{file.url}</p>
                                        {file.type && <p className="text-xs text-gray-600">{file.type}</p>}
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="p-6 border-t border-gray-800 flex justify-end gap-3 bg-gray-900/50">
                            <button onClick={() => { setDetectedResources([]); setSelectedResources(new Set()); }} className="px-4 py-2 text-gray-400 hover:text-white transition-colors">Clear List</button>
                            <button
                                onClick={downloadSelected}
                                disabled={selectedResources.size === 0}
                                className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium transition-all shadow-lg shadow-blue-600/20 flex items-center gap-2"
                            >
                                <Download size={18} />
                                Download Selected ({selectedResources.size})
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {/* Deep Data Modal */}
            {showDataModal && (
                <div className="absolute inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8 z-[60]">
                    <div className="bg-gray-900 w-full max-w-4xl h-[80vh] rounded-2xl border border-gray-800 flex flex-col shadow-2xl overflow-hidden">
                        <div className="p-6 border-b border-gray-800 flex justify-between items-center bg-gray-900/50">
                            <h2 className="text-xl font-bold flex items-center gap-2">
                                <Database size={20} className="text-blue-400" />
                                Deep Analysis
                                <span className="text-sm font-normal text-gray-400">({deepData.length} captured objects)</span>
                            </h2>
                            <button onClick={() => setShowDataModal(false)} className="text-gray-400 hover:text-white transition-colors">
                                <X size={24} />
                            </button>
                        </div>

                        <div className="flex-1 flex min-h-0">
                            {/* List Side */}
                            <div className="w-1/3 border-r border-gray-800 overflow-y-auto custom-scrollbar p-2 space-y-2">
                                {deepData.length === 0 && (
                                    <div className="text-center text-gray-500 py-12 text-sm">No JSON data captured yet. Browse a site to see API calls.</div>
                                )}
                                {deepData.map((item) => (
                                    <div 
                                      key={item.id}
                                      onClick={() => setSelectedData(item)}
                                      className={`p-3 rounded-lg cursor-pointer transition-all border ${selectedData?.id === item.id ? 'bg-blue-900/40 border-blue-500' : 'bg-gray-800/50 border-transparent hover:bg-gray-800'}`}
                                    >
                                        <div className="flex justify-between items-start gap-2">
                                            <span className="text-[10px] font-bold text-gray-400 uppercase">{item.method}</span>
                                            <span className="text-[10px] text-gray-500">{item.timestamp}</span>
                                        </div>
                                        <div className="text-xs font-medium truncate text-gray-200 mt-1">{item.url}</div>
                                        <div className="text-[10px] text-gray-500 mt-1">{item.status} • {item.content_type.split(';')[0]}</div>
                                    </div>
                                ))}
                            </div>

                            {/* Viewer Side */}
                            <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-gray-950/50">
                                {selectedData ? (
                                    <div className="space-y-6">
                                        <div>
                                            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                                                <Info size={12} /> General Information
                                            </h3>
                                            <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl space-y-2">
                                                <p className="text-sm text-gray-300 break-all"><span className="text-gray-500">URL:</span> {selectedData.url}</p>
                                                <p className="text-sm text-gray-300"><span className="text-gray-500">Method:</span> {selectedData.method}</p>
                                                <p className="text-sm text-gray-300"><span className="text-gray-500">Status:</span> {selectedData.status}</p>
                                            </div>
                                        </div>

                                        {selectedData.request && (
                                            <div>
                                                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                                                    <ArrowRight size={12} className="text-blue-400" /> Request Payload
                                                </h3>
                                                <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl overflow-x-auto">
                                                    <pre className="text-xs text-blue-300 font-mono">
                                                        {JSON.stringify(selectedData.request, null, 2)}
                                                    </pre>
                                                </div>
                                            </div>
                                        )}

                                        <div>
                                            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                                                <ArrowLeft size={12} className="text-emerald-400" /> Response Body
                                            </h3>
                                            <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl overflow-x-auto relative">
                                                <button 
                                                  onClick={() => {
                                                      const blob = new Blob([JSON.stringify(selectedData.response, null, 2)], { type: 'application/json' });
                                                      const url = URL.createObjectURL(blob);
                                                      const a = document.createElement('a');
                                                      a.href = url;
                                                      a.download = `response_${selectedData.id}.json`;
                                                      a.click();
                                                  }}
                                                  className="absolute top-2 right-2 p-2 bg-gray-800 hover:bg-gray-700 rounded-md text-gray-400 hover:text-white transition-all shadow-lg"
                                                  title="Save JSON"
                                                >
                                                  <Download size={14} />
                                                </button>
                                                <pre className="text-xs text-emerald-300 font-mono">
                                                    {JSON.stringify(selectedData.response, null, 2)}
                                                </pre>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="h-full flex flex-col items-center justify-center text-gray-600 space-y-4">
                                        <Code size={48} className="opacity-20" />
                                        <p>Select an item from the list to view its contents</p>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="p-4 border-t border-gray-800 flex justify-between items-center bg-gray-900/50">
                            <p className="text-[10px] text-gray-500 max-w-sm">
                                Tip: Use Deep Analysis to extract GraphQL, JSON APIs, and hidden internal data that regular scrapers miss.
                            </p>
                            <button 
                              onClick={() => { setDeepData([]); setSelectedData(null); }} 
                              className="px-4 py-2 text-xs text-gray-400 hover:text-red-400 transition-colors"
                            >
                                Clear All Data
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
