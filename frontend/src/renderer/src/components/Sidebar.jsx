import React from 'react';
import { Home, Settings, Download } from 'lucide-react';

export default function Sidebar({ activeTab, setActiveTab }) {
    const tabs = [
        { id: 'main', icon: Home, label: 'Home' },
        { id: 'downloads', icon: Download, label: 'Downloads' },
        { id: 'settings', icon: Settings, label: 'Settings' }
    ];

    return (
        <div className="w-16 h-screen bg-gray-900 flex flex-col items-center py-4 space-y-4 border-r border-gray-800">
            {tabs.map((tab) => {
                const Icon = tab.icon;
                return (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`p-3 rounded-xl transition-all ${activeTab === tab.id
                                ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/30'
                                : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                            }`}
                        title={tab.label}
                    >
                        <Icon size={24} />
                    </button>
                );
            })}
        </div>
    );
}
