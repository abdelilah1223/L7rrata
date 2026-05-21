import React, { useState, useEffect, useMemo, useRef } from 'react';
import { File, CheckCircle, Clock, Play, Pause, XCircle, AlertCircle, Trash2, ExternalLink, Folder, Eye, X, MoreVertical, StopCircle, RefreshCw, Image as ImageIcon, Video, Music, FileText } from 'lucide-react';

export default function DownloadsTab() {
    const updateBuffer = useRef({});
    const [downloads, setDownloads] = useState({});
    const [previewFile, setPreviewFile] = useState(null);
    const [filterType, setFilterType] = useState('all'); // all, image, video, audio, document, other

    useEffect(() => {
        // Fetch initial state
        window.api.getDownloads().then(initial => {
            const map = {};
            initial.forEach(d => map[d.id] = d);
            setDownloads(map);
        });

        // BUFFERED UPDATE HANDLER (Performance Booster)
        const handleUpdate = (entry) => {
            updateBuffer.current[entry.id] = entry;
        };

        // Flush buffer every 500ms to avoid React render thrashing
        const flushTimer = setInterval(() => {
            if (Object.keys(updateBuffer.current).length === 0) return;
            setDownloads(prev => {
                const next = { ...prev, ...updateBuffer.current };
                updateBuffer.current = {};
                return next;
            });
        }, 500);

        const removeListener = window.api.onDownloadUpdated ? window.api.onDownloadUpdated(handleUpdate) : () => { };
        const removeRemoveListener = window.api.onDownloadRemoved ? window.api.onDownloadRemoved((id) => {
            setDownloads(prev => {
                const search = { ...prev };
                delete search[id];
                return search;
            });
        }) : () => { };
        const removeClearListener = window.api.onDownloadsCleared ? window.api.onDownloadsCleared(() => {
            setDownloads({});
        }) : () => { };

        return () => {
            clearInterval(flushTimer);
            removeListener();
            removeRemoveListener();
            removeClearListener();
        };
    }, []);

    const sendControl = (action, id) => {
        window.api.sendDownloadControl({ action, id });
    };

    const openFile = (file, type = 'open') => {
        // type: 'open' (default app), 'show' (folder), 'browser' (external)
        if (type === 'browser') {
            // For HTML, we might want to open in system browser
            // Using shell.openExternal logic (handled by open-file with type='open' usually works for html too)
            window.api.openFile({ id: file.id, path: file.path, type: 'open' });
        } else {
            window.api.openFile({ id: file.id, path: file.path, type });
        }
    };

    const downloadList = useMemo(() => {
        const list = Object.values(downloads).sort((a, b) => b.startTime - a.startTime);
        if (filterType === 'all') return list;
        return list.filter(d => {
            const type = d.type || '';
            if (filterType === 'image') return type.startsWith('image/');
            if (filterType === 'video') return type.startsWith('video/');
            if (filterType === 'audio') return type.startsWith('audio/');
            if (filterType === 'document') return type.includes('pdf') || type.includes('text') || type.includes('json') || type.includes('xml');
            return !type.startsWith('image/') && !type.startsWith('video/') && !type.startsWith('audio/');
        });
    }, [downloads, filterType]);

    // Grouping downloads by main folder
    const groupedDownloads = useMemo(() => {
        return downloadList.reduce((acc, file) => {
            const parts = file.path ? file.path.split(/[\\/]/) : [];
            const folderName = parts.length > 2 ? parts[parts.length - 3] : 'Other'; // e.g., hostname_date
            if (!acc[folderName]) acc[folderName] = [];
            acc[folderName].push(file);
            return acc;
        }, {});
    }, [downloadList]);

    const sortedFolders = useMemo(() => Object.keys(groupedDownloads).sort(), [groupedDownloads]);

    // Small Thumbnail Helper
    const renderThumbnail = (file) => {
        const type = file.type || '';
        const safePath = 'local://' + file.path;

        if (type.startsWith('image/')) {
            return <img src={safePath} className="w-full h-full object-cover rounded-lg" alt="" />;
        }
        if (type.startsWith('video/')) {
            return <video src={safePath} className="w-full h-full object-cover rounded-lg" />;
        }
        if (type.includes('html')) {
            return <div className="w-full h-full flex items-center justify-center bg-orange-500/20 text-orange-500 rounded-lg font-bold text-xs">HTML</div>;
        }

        let Icon = File;
        let colorClass = "text-blue-500 bg-blue-500/20";

        if (type.startsWith('audio/')) { Icon = Music; colorClass = "text-purple-500 bg-purple-500/20"; }
        else if (type.includes('pdf') || type.includes('document')) { Icon = FileText; colorClass = "text-yellow-500 bg-yellow-500/20"; }

        return <div className={`w-full h-full flex items-center justify-center rounded-lg ${colorClass}`}><Icon size={24} /></div>;
    };

    // Render Preview Content (Modal)
    const renderPreviewContent = (file) => {
        const type = file.type || '';
        const safePath = 'local://' + file.path;

        if (type.startsWith('image/')) {
            return (
                <div className="flex justify-center items-center bg-gray-900 rounded-lg p-4 h-64">
                    <img src={safePath} alt={file.name} className="max-h-full max-w-full object-contain" />
                </div>
            );
        }
        if (type.startsWith('video/') || type.startsWith('audio/')) {
            return (
                <div className="flex justify-center items-center bg-gray-900 rounded-lg p-4 h-64">
                    <video controls src={safePath} className="max-h-full max-w-full" />
                </div>
            );
        }
        if (type.includes('html')) {
            return (
                <div className="flex flex-col items-center justify-center bg-gray-900 rounded-lg p-8 h-64 text-center">
                    <File size={48} className="mb-4 text-orange-500" />
                    <p className="mb-4 text-gray-300">HTML Document</p>
                    <button
                        onClick={() => openFile(file, 'open')}
                        className="px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg font-medium text-white transition-colors"
                    >
                        Open in Browser
                    </button>
                    <div className="mt-4 w-full h-32 bg-white rounded overflow-hidden relative">
                        <iframe src={safePath} className="w-full h-full border-none pointer-events-none select-none opacity-50" title="preview" />
                    </div>
                </div>
            );
        }

        return (
            <div className="flex flex-col items-center justify-center bg-gray-900 rounded-lg p-8 h-64 text-center">
                <File size={48} className="mb-4 text-gray-500" />
                <p className="mb-4 text-gray-300">Preview not available</p>
                <div className="flex gap-4">
                    <button onClick={() => openFile(file, 'open')} className="text-blue-400 hover:underline">Open File</button>
                    <button onClick={() => openFile(file, 'show')} className="text-blue-400 hover:underline">Show in Folder</button>
                </div>
            </div>
        );
    };

    return (
        <div className="h-full p-8 bg-gray-950 text-white overflow-hidden flex flex-col relative">
            <header className="flex flex-col gap-4 mb-6">
                <div className="flex justify-between items-center">
                    <h1 className="text-3xl font-bold">Downloads</h1>
                    <div className="flex gap-2">
                        <button onClick={() => window.api.sendDownloadControl({ action: 'resume-all' })} className="p-2 hover:bg-gray-800 rounded-lg text-green-400 hover:text-green-300 transition-colors" title="Resume All">
                            <Play size={20} />
                        </button>
                        <button onClick={() => window.api.sendDownloadControl({ action: 'pause-all' })} className="p-2 hover:bg-gray-800 rounded-lg text-yellow-400 hover:text-yellow-300 transition-colors" title="Pause All">
                            <Pause size={20} />
                        </button>
                        <button onClick={() => window.api.sendDownloadControl({ action: 'cancel-all' })} className="p-2 hover:bg-gray-800 rounded-lg text-red-400 hover:text-red-300 transition-colors" title="Cancel All">
                            <XCircle size={20} />
                        </button>
                        <div className="w-px h-6 bg-gray-800 mx-2"></div>
                        <button onClick={() => window.api.sendDownloadControl({ action: 'remove-all' })} className="p-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors" title="Clear All Lists">
                            <Trash2 size={20} />
                        </button>
                    </div>
                </div>

                {/* Filters */}
                <div className="flex gap-2 text-sm overflow-x-auto custom-scrollbar pb-1">
                    {['all', 'image', 'video', 'audio', 'document', 'other'].map(type => (
                        <button
                            key={type}
                            onClick={() => setFilterType(type)}
                            className={`px-4 py-2 rounded-full capitalize transition-all font-medium border ${filterType === type
                                ? 'bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-500/20'
                                : 'bg-gray-900 border-gray-800 text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                                }`}
                        >
                            {type}
                        </button>
                    ))}
                </div>
            </header>

            <div className="flex-1 overflow-y-auto space-y-6 custom-scrollbar pr-2">
                {sortedFolders.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-gray-500">
                        <File size={48} className="mb-4 opacity-20" />
                        <p>No downloads found for this filter.</p>
                    </div>
                ) : (
                    sortedFolders.map(folderName => (
                        <div key={folderName} className="space-y-3">
                            <div className="flex items-center gap-2 px-1 text-gray-400 font-semibold text-sm">
                                <Folder size={16} />
                                <span className="uppercase tracking-wider">{folderName}</span>
                                <div className="h-px flex-1 bg-gray-800 ml-2"></div>
                            </div>
                            {groupedDownloads[folderName].map((file) => {
                                const progress = file.total > 0 ? (file.received / file.total) * 100 : 0;
                                const isIndeterminate = file.total === 0 && file.state === 'downloading';

                                return (
                                    <div
                                        key={file.id}
                                        onClick={() => setPreviewFile(file)}
                                        className="bg-gray-900 hover:bg-gray-800 p-4 rounded-xl border border-gray-800 flex items-center gap-4 transition-all cursor-pointer group"
                                    >
                                        {/* Icon / Thumbnail */}
                                        <div className="w-16 h-16 shrink-0">
                                            {renderThumbnail(file)}
                                        </div>

                                        {/* Info */}
                                        <div className="flex-1 min-w-0">
                                            <h4 className="font-medium text-white truncate mb-1" title={file.name}>
                                                {file.name || 'Unknown File'}
                                            </h4>
                                            <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
                                                <span className="truncate max-w-[200px]" title={file.url}>{file.url}</span>
                                                <span>•</span>
                                                <span>{(file.received / 1024 / 1024).toFixed(2)} MB</span>
                                                {file.total > 0 && <span> / {(file.total / 1024 / 1024).toFixed(2)} MB</span>}
                                                <span>•</span>
                                                <span className="capitalize">{file.state}</span>
                                            </div>

                                            {/* Progress Bar */}
                                            <div className="h-1.5 w-full bg-gray-700 rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full rounded-full transition-all duration-300 ${file.state === 'completed' ? 'bg-green-500' :
                                                        file.state === 'error' ? 'bg-red-500' :
                                                            'bg-blue-500'
                                                        } ${isIndeterminate ? 'animate-progress-indeterminate' : ''}`}
                                                    style={{ width: `${progress}%` }}
                                                ></div>
                                            </div>
                                        </div>

                                        {/* Controls */}
                                        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                                            <button onClick={() => sendControl('remove', file.id)} className="p-2 hover:bg-gray-700 rounded-full text-gray-500 hover:text-white" title="Remove from list">
                                                <X size={16} />
                                            </button>
                                            
                                            <div className="w-px h-4 bg-gray-700 mx-1"></div>

                                            {file.state === 'completed' ? (
                                                <>
                                                    <button onClick={() => openFile(file, 'show')} className="p-2 hover:bg-gray-700 rounded-full text-blue-400 hover:text-blue-300" title="Show in Folder">
                                                        <Folder size={18} />
                                                    </button>
                                                    <button onClick={() => openFile(file, 'open')} className="p-2 hover:bg-gray-700 rounded-full text-green-400 hover:text-green-300" title="Open File">
                                                        <ExternalLink size={18} />
                                                    </button>
                                                </>
                                            ) : (
                                                <>
                                                    {file.state === 'downloading' ? (
                                                        <button onClick={() => sendControl('pause', file.id)} className="p-2 hover:bg-gray-700 rounded-full text-yellow-400" title="Pause">
                                                            <Pause size={18} />
                                                        </button>
                                                    ) : (
                                                        <button 
                                                            onClick={() => file.state === 'pending' || file.state === 'error' || file.state === 'cancelled' ? sendControl('start', file.id) : sendControl('resume', file.id)} 
                                                            className="p-2 hover:bg-gray-700 rounded-full text-green-400" 
                                                            title="Start / Resume"
                                                        >
                                                            <Play size={18} />
                                                        </button>
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    ))
                )}
            </div>

            {/* Preview Modal */}
            {previewFile && (
                <div className="absolute inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8 animate-fade-in">
                    <div className="bg-gray-950 border border-gray-800 rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden flex flex-col max-h-full">
                        <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-gray-900/50">
                            <h3 className="font-bold text-lg truncate pr-4">{previewFile.name}</h3>
                            <button onClick={() => setPreviewFile(null)} className="p-2 hover:bg-gray-800 rounded-full transition-colors">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="p-6 overflow-y-auto custom-scrollbar">
                            {renderPreviewContent(previewFile)}
                        </div>

                        <div className="p-4 border-t border-gray-800 bg-gray-900/50 flex justify-end gap-3">
                            <button onClick={() => openFile(previewFile, 'show')} className="px-4 py-2 hover:bg-gray-800 rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
                                <Folder size={16} /> Show in Folder
                            </button>
                            <button onClick={() => openFile(previewFile, 'open')} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium text-white transition-colors flex items-center gap-2">
                                <ExternalLink size={16} /> Open
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
