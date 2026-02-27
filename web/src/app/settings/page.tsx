"use client";

import { Settings as SettingsIcon, Database, KeyRound, Cloud, Server, ArrowRight, Paintbrush } from "lucide-react";
import { useThemeStore } from "@/components/ThemeProvider";

export default function SettingsPage() {
  const { theme, setTheme } = useThemeStore();

  return (
    <div className="max-w-6xl mx-auto space-y-10 animate-in fade-in duration-500 pb-12">
      <header className="flex justify-between items-end border-b border-crust/30 pb-4">
        <div>
          <h1 className="text-4xl font-display text-mauve tracking-wider">Settings</h1>
          <p className="text-sm font-sans text-text/60 mt-1 uppercase tracking-widest font-mono">
            System Configuration
          </p>
        </div>
        <button className="flex items-center space-x-2 bg-mauve/10 hover:bg-mauve/20 text-mauve border border-mauve/30 px-5 py-2.5 rounded-sm font-medium transition-colors">
          <Server className="w-4 h-4" />
          <span>Test Connections</span>
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Navigation Sidebar for Settings - using lg:col-span-3 */}
        <div className="lg:col-span-3 space-y-2">
           <nav className="flex flex-col space-y-1">
             <a href="#" className="px-4 py-2.5 text-text/60 hover:text-text hover:bg-mantle border-l-2 border-transparent font-medium text-sm transition-colors">
               Aesthetic Controls
             </a>
             <a href="#" className="px-4 py-2.5 bg-mauve/10 text-mauve border-l-2 border-mauve font-medium text-sm flex items-center justify-between">
               <span>Integrations</span> <ArrowRight className="w-4 h-4 opacity-50" />
             </a>
             <a href="#" className="px-4 py-2.5 text-text/60 hover:text-text hover:bg-mantle border-l-2 border-transparent font-medium text-sm transition-colors">
               Vault Profiles
             </a>
             <a href="#" className="px-4 py-2.5 text-text/60 hover:text-text hover:bg-mantle border-l-2 border-transparent font-medium text-sm transition-colors">
               R2 Storage
             </a>
           </nav>
        </div>

        {/* Form Content - using lg:col-span-9 */}
        <div className="lg:col-span-9 space-y-8">
          
          <div className="bg-mantle border border-crust/20 rounded-lg p-8 shadow-sm">
             <div className="flex items-center space-x-3 text-text mb-6">
               <Paintbrush className="w-6 h-6 text-mauve" />
               <h2 className="text-xl font-serif">Aesthetic Preferences</h2>
             </div>
             
             <div className="space-y-4">
               <div>
                 <label className="block text-sm font-mono text-text/60 mb-2 uppercase tracking-wider">Active Preset</label>
                 <div className="flex space-x-3">
                    <button 
                      onClick={() => setTheme("catppuccin")}
                      className={`px-4 py-2 rounded-md text-sm font-medium transition-colors border ${theme === 'catppuccin' ? 'bg-mauve text-crust border-mauve' : 'bg-crust text-text/60 border-crust/50 hover:border-mauve/30'}`}
                    >
                      Catppuccin Mocha
                    </button>
                    <button 
                      onClick={() => setTheme("midnight-luxe")}
                      className={`px-4 py-2 rounded-md text-sm font-medium transition-colors border ${theme === 'midnight-luxe' ? 'bg-mauve text-crust border-mauve' : 'bg-crust text-text/60 border-crust/50 hover:border-mauve/30'}`}
                    >
                      Midnight Luxe
                    </button>
                    <button 
                      onClick={() => setTheme("light")}
                      className={`px-4 py-2 rounded-md text-sm font-medium transition-colors border ${theme === 'light' ? 'bg-mauve text-crust border-mauve' : 'bg-crust text-text/60 border-crust/50 hover:border-mauve/30'}`}
                    >
                      Light Grid
                    </button>
                 </div>
                 <p className="text-sm font-sans text-text/40 mt-3">Saves to local browser storage instantly.</p>
               </div>
             </div>
          </div>

          <div className="bg-mantle border border-crust/20 rounded-lg p-8 shadow-sm">
             <div className="flex items-center space-x-3 text-text mb-6">
               <KeyRound className="w-6 h-6 text-teal" />
               <h2 className="text-xl font-serif">Platform Integrations</h2>
             </div>
             
             <div className="space-y-6">
                <div className="flex items-center justify-between border-b border-crust/30 pb-6">
                   <div>
                      <h3 className="font-medium text-lg text-text">TikTok API</h3>
                      <p className="text-sm text-text/50 mt-1">Configure your TikTok for Business credentials.</p>
                   </div>
                   <button className="px-4 py-2 bg-crust border border-crust/50 hover:border-teal/50 rounded-md text-sm text-text transition-colors">
                     Connected
                   </button>
                </div>
                
                <div className="flex items-center justify-between border-b border-crust/30 pb-6">
                   <div>
                      <h3 className="font-medium text-lg text-text">YouTube V3</h3>
                      <p className="text-sm text-text/50 mt-1">Manage YouTube Data API OAuth scopes.</p>
                   </div>
                   <button className="px-4 py-2 bg-mauve text-crust font-medium rounded-md text-sm transition-colors hover:bg-mauve/90">
                     Connect Account
                   </button>
                </div>
                
                <div className="flex items-center justify-between pb-2">
                   <div>
                      <h3 className="font-medium text-lg text-text">Instagram Graph</h3>
                      <p className="text-sm text-text/50 mt-1">Link an Instagram Professional Account via Facebook.</p>
                   </div>
                   <button className="px-4 py-2 bg-mauve text-crust font-medium rounded-md text-sm transition-colors hover:bg-mauve/90">
                     Connect Account
                   </button>
                </div>
             </div>
          </div>

          <div className="bg-mantle border border-crust/20 rounded-lg p-8 shadow-sm">
             <div className="flex items-center space-x-3 text-text mb-6">
               <Database className="w-6 h-6 text-mauve" />
               <h2 className="text-xl font-serif">Local Sync</h2>
             </div>
             
             <div className="space-y-4">
               <div>
                 <label className="block text-sm font-mono text-text/60 mb-2 uppercase tracking-wider">Vault Path</label>
                 <input 
                   disabled
                   type="text" 
                   defaultValue="/home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/vault" 
                   className="w-full bg-crust border border-crust/50 rounded-md px-4 py-3 text-text text-sm focus:outline-none focus:border-mauve/50 transition-colors opacity-70"
                 />
               </div>
               <div>
                 <label className="block text-sm font-mono text-text/60 mb-2 uppercase tracking-wider mt-6">Supabase URL</label>
                 <input 
                   type="text" 
                   defaultValue="https://nntjnjqzzhcmhwhqfblf.supabase.co" 
                   className="w-full bg-crust border border-crust/50 rounded-md px-4 py-3 text-text text-sm focus:outline-none focus:border-mauve/50 transition-colors"
                 />
               </div>
             </div>
          </div>
          
        </div>
      </div>
    </div>
  );
}
