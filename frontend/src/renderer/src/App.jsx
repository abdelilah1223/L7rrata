import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import MainTab from './pages/MainTab';
import SettingsTab from './pages/SettingsTab';
import DownloadsTab from './pages/DownloadsTab';

function App() {
    const [activeTab, setActiveTab] = useState('main');

    return (
        <div className="flex h-screen w-screen bg-gray-950 overflow-hidden">
            <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

            <main className="flex-1 h-full relative">
                {/* Use display: none to persist the MainTab (Browser) state */}
                <div style={{ display: activeTab === 'main' ? 'block' : 'none', height: '100%' }}>
                    <MainTab />
                </div>

                {activeTab === 'settings' && <SettingsTab />}
                {activeTab === 'downloads' && <DownloadsTab />}
            </main>
        </div>
    );
}

export default App;
