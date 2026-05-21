import React, { useState, useEffect } from 'react';
import { Save, FolderOpen, Shield, ShieldOff } from 'lucide-react';

export default function SettingsTab() {
    const [settings, setSettings] = useState({
        maxFileSize: 50 * 1024 * 1024,
        autoDownload: true,
        downloadPath: '',
        proxy: {
            enabled: false,
            type: 'http',
            host: '',
            port: '',
            username: '',
            password: ''
        }
    });

    useEffect(() => {
        window.api.getSettings().then(loaded => {
            setSettings(prev => ({
                ...prev,
                ...loaded,
                proxy: { ...prev.proxy, ...(loaded.proxy || {}) }
            }));
        });
    }, []);

    // Auto-Save (debounced)
    useEffect(() => {
        const timer = setTimeout(() => {
            window.api.saveSettings(settings);
        }, 800);
        return () => clearTimeout(timer);
    }, [settings]);

    const handleSave = () => {
        window.api.saveSettings(settings);
    };

    const handleOpenFolder = () => {
        window.api.openFolder();
    };

    const updateProxy = (field, value) => {
        setSettings(prev => ({
            ...prev,
            proxy: { ...prev.proxy, [field]: value }
        }));
    };

    return (
        <div className="h-full p-8 bg-gray-950 text-white overflow-y-auto custom-scrollbar">
            <div className="max-w-3xl mx-auto pb-16">
                <h1 className="text-3xl font-bold mb-8">Settings</h1>

                <div className="space-y-6">
                {/* Max File Size */}
                <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800">
                    <label className="block text-sm font-medium text-gray-400 mb-2">
                        Max File Size (MB)
                    </label>
                    <input
                        type="number"
                        value={Math.round(settings.maxFileSize / (1024 * 1024))}
                        onChange={(e) => setSettings({ ...settings, maxFileSize: Number(e.target.value) * 1024 * 1024 })}
                        className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                    />
                    <p className="text-xs text-gray-500 mt-2">
                        Files larger than this will not be downloaded automatically.
                    </p>
                </div>

                {/* Auto Download */}
                <div className="bg-gray-900 p-6 rounded-2xl border border-gray-800 flex items-center justify-between">
                    <div>
                        <h3 className="font-medium text-white">Auto Download</h3>
                        <p className="text-sm text-gray-400">
                            Automatically download detected resources without asking.
                        </p>
                    </div>
                    <button
                        onClick={() => setSettings({ ...settings, autoDownload: !settings.autoDownload })}
                        className={`w-14 h-8 rounded-full p-1 transition-colors ${settings.autoDownload ? 'bg-blue-600' : 'bg-gray-700'}`}
                    >
                        <div className={`w-6 h-6 bg-white rounded-full shadow-md transform transition-transform ${settings.autoDownload ? 'translate-x-6' : 'translate-x-0'}`} />
                    </button>
                </div>

                {/* ── Proxy Settings ───────────────────────────────────────────────── */}
                <div className="bg-gray-900 rounded-2xl border border-gray-800 overflow-hidden">
                    {/* Proxy Header / Toggle */}
                    <div className="p-6 flex items-center justify-between border-b border-gray-800">
                        <div className="flex items-center gap-3">
                            {settings.proxy?.enabled
                                ? <Shield size={20} className="text-emerald-400" />
                                : <ShieldOff size={20} className="text-gray-500" />
                            }
                            <div>
                                <h3 className="font-medium text-white">Proxy</h3>
                                <p className="text-sm text-gray-400">Route all traffic through a proxy server.</p>
                            </div>
                        </div>
                        <button
                            onClick={() => updateProxy('enabled', !settings.proxy?.enabled)}
                            className={`w-14 h-8 rounded-full p-1 transition-colors ${settings.proxy?.enabled ? 'bg-emerald-600' : 'bg-gray-700'}`}
                        >
                            <div className={`w-6 h-6 bg-white rounded-full shadow-md transform transition-transform ${settings.proxy?.enabled ? 'translate-x-6' : 'translate-x-0'}`} />
                        </button>
                    </div>

                    {/* Proxy Fields — shown only when proxy is enabled */}
                    {settings.proxy?.enabled && (
                        <div className="p-6 space-y-4">
                            {/* Proxy Type */}
                            <div>
                                <label className="block text-xs font-medium text-gray-400 mb-1.5">Proxy Type</label>
                                <div className="flex gap-3">
                                    {['http', 'socks5'].map(type => (
                                        <button
                                            key={type}
                                            onClick={() => updateProxy('type', type)}
                                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${settings.proxy.type === type
                                                ? 'bg-blue-600 text-white'
                                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                                            }`}
                                        >
                                            {type.toUpperCase()}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Host & Port */}
                            <div className="flex gap-3">
                                <div className="flex-1">
                                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Host</label>
                                    <input
                                        type="text"
                                        value={settings.proxy.host}
                                        onChange={e => updateProxy('host', e.target.value)}
                                        placeholder="127.0.0.1"
                                        className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                                    />
                                </div>
                                <div className="w-28">
                                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Port</label>
                                    <input
                                        type="text"
                                        value={settings.proxy.port}
                                        onChange={e => updateProxy('port', e.target.value)}
                                        placeholder="8080"
                                        className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                                    />
                                </div>
                            </div>

                            {/* Auth (optional) */}
                            <div>
                                <label className="block text-xs font-medium text-gray-400 mb-1.5">Authentication <span className="text-gray-600">(optional)</span></label>
                                <div className="flex gap-3">
                                    <input
                                        type="text"
                                        value={settings.proxy.username}
                                        onChange={e => updateProxy('username', e.target.value)}
                                        placeholder="Username"
                                        className="flex-1 bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                                    />
                                    <input
                                        type="password"
                                        value={settings.proxy.password}
                                        onChange={e => updateProxy('password', e.target.value)}
                                        placeholder="Password"
                                        className="flex-1 bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                                    />
                                </div>
                            </div>

                            {/* Preview */}
                            {settings.proxy.host && settings.proxy.port && (
                                <div className="bg-gray-950 rounded-lg px-4 py-2.5 border border-gray-700 text-xs text-emerald-400 font-mono">
                                    {settings.proxy.type}://{settings.proxy.username ? `${settings.proxy.username}:***@` : ''}{settings.proxy.host}:{settings.proxy.port}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* Actions */}
                <div className="flex gap-4">
                    <button
                        onClick={handleSave}
                        className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 rounded-xl font-medium transition-all shadow-lg shadow-blue-600/20"
                    >
                        <Save size={18} />
                        Save Settings
                    </button>

                    <button
                        onClick={handleOpenFolder}
                        className="flex items-center gap-2 px-6 py-3 bg-gray-800 hover:bg-gray-700 rounded-xl font-medium transition-all border border-gray-700"
                    >
                        <FolderOpen size={18} />
                        Open Downloads Folder
                    </button>
                </div>
            </div>
        </div>
    </div>
    );
}
