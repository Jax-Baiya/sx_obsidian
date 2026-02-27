"use client";

import { Terminal as TerminalIcon, Play, RefreshCw, UploadCloud, Database, RefreshCcw, CheckCircle2, Clock } from "lucide-react";
import { useState, useEffect } from "react";

// Mock metric type for the dashboard cards
type JobMetric = {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  lastRun: string;
  status: "idle" | "running" | "success" | "error";
};

export default function CliConsolePage() {
  const [metrics, setMetrics] = useState<JobMetric[]>([
    {
      id: "vault-sync",
      name: "Sync Local Vault",
      description: "Scans the markdown payload for new assets and metadata.",
      icon: <Database className="w-5 h-5 text-teal" />,
      lastRun: "2 mins ago",
      status: "idle"
    },
    {
      id: "r2-upload",
      name: "Sync R2 Media",
      description: "Uploads missing video files to Cloudflare storage.",
      icon: <UploadCloud className="w-5 h-5 text-mauve" />,
      lastRun: "Yesterday",
      status: "idle"
    },
    {
      id: "schedule-gen",
      name: "Process Scheduling",
      description: "Generates JSON artifacts for draft reviews.",
      icon: <RefreshCw className="w-5 h-5 text-emerald-400" />,
      lastRun: "5 mins ago",
      status: "idle"
    },
    {
      id: "postgres-mirror",
      name: "Mirror Cloud DB",
      description: "Pulls remote state from Supabase to local SQLite.",
      icon: <RefreshCcw className="w-5 h-5 text-text/60" />,
      lastRun: "Just now",
      status: "idle"
    }
  ]);

  const [logs, setLogs] = useState<string[]>([
    "SX_OBSIDIAN System Ready.",
    "Awaiting manual triggers..."
  ]);

  const dispatchCommand = async (id: string) => {
    // Set status to running
    setMetrics(prev => prev.map(m => m.id === id ? { ...m, status: "running" } : m));
    
    const metric = metrics.find(m => m.id === id);
    setLogs(prev => [`> Starting job: ${metric?.name}...`, ...prev].slice(0, 10));

    // Map the Dashboard IDs to actual FastAPI routes
    let endpoint = "";
    if (id === "vault-sync") endpoint = "/admin/sync-vault";
    else if (id === "r2-upload") endpoint = "/media/sync-all";
    else if (id === "schedule-gen") endpoint = "/scheduler/process-all";
    else if (id === "postgres-mirror") endpoint = "/admin/bootstrap/schema"; 
    
    try {
      // Fire the fetch request directly to the local python backend
      const res = await fetch(`http://localhost:8123${endpoint}`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "X-SX-Source-ID": "assets_1"
        },
        body: id === "postgres-mirror" ? JSON.stringify({ source_id: "assets_1" }) : undefined
      });
      
      const data = await res.json().catch(() => ({}));
      
      if (res.ok && data.ok !== false) {
        setMetrics(prev => prev.map(m => m.id === id ? { ...m, status: "success", lastRun: "Just now" } : m));
        setLogs(prev => [`✓ Success: ${data.message || metric?.name + " completed."}`, ...prev].slice(0, 10));
      } else {
        throw new Error(data.message || data.detail || "API Error");
      }
    } catch (err: any) {
      setMetrics(prev => prev.map(m => m.id === id ? { ...m, status: "error" } : m));
      setLogs(prev => [`! Error: ${err.message}`, ...prev].slice(0, 10));
    } finally {
      // Reset back to idle after a moment
      setTimeout(() => {
        setMetrics(prev => prev.map(m => m.id === id ? { ...m, status: "idle" } : m));
      }, 5000);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500 pb-12">
      <header className="flex justify-between items-end border-b border-crust/30 pb-4">
        <div>
          <h1 className="text-4xl font-display text-mauve tracking-wider flex items-center gap-3">
             <TerminalIcon className="w-8 h-8" /> Console Dashboard
          </h1>
          <p className="text-sm font-sans text-text/60 mt-1 uppercase tracking-widest font-mono">
            System Operations & Metrics
          </p>
        </div>
      </header>

      {/* Grid of Action Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        {metrics.map((metric) => (
          <div key={metric.id} className="bg-mantle border border-crust/30 rounded-lg p-6 flex flex-col justify-between shadow-sm hover:shadow-md transition-shadow">
            <div>
              <div className="flex justify-between items-start mb-4">
                <div className="p-3 bg-crust rounded-md">
                  {metric.icon}
                </div>
                {metric.status === "running" ? (
                  <span className="flex h-3 w-3 relative">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-mauve opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-mauve"></span>
                  </span>
                ) : metric.status === "success" ? (
                  <CheckCircle2 className="w-5 h-5 text-teal" />
                ) : null}
              </div>
              
              <h3 className="text-lg font-serif text-text mb-1">{metric.name}</h3>
              <p className="text-sm text-text/60 line-clamp-2 min-h-[40px]">{metric.description}</p>
            </div>
            
            <div className="mt-6 pt-4 border-t border-crust/20 flex items-center justify-between">
              <div className="flex items-center text-xs font-mono text-text/40">
                <Clock className="w-3 h-3 mr-1" />
                {metric.lastRun}
              </div>
              <button 
                onClick={() => dispatchCommand(metric.id)}
                disabled={metric.status === "running"}
                className={`flex items-center justify-center p-2 rounded-full transition-colors ${
                  metric.status === "running" ? 'bg-crust text-text/20 cursor-not-allowed' : 'bg-mauve/10 hover:bg-mauve/20 text-mauve'
                }`}
              >
                <Play className="w-4 h-4 fill-current ml-[2px]" />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Mini Event Log */}
      <div className="bg-mantle border border-crust/30 rounded-lg p-6 mt-8">
        <h2 className="text-sm font-mono text-text/50 uppercase tracking-widest mb-4">Recent Events</h2>
        <div className="bg-[#0b0b12] border border-crust/50 rounded-md h-48 font-mono text-sm p-4 overflow-y-auto shadow-inner flex flex-col">
          <div className="text-text/70 space-y-2">
            {logs.map((log, idx) => (
              <div key={idx} className={`${
                log.startsWith('>') ? 'text-mauve font-semibold' : 
                log.startsWith('✓') ? 'text-teal' : 
                log.startsWith('!') ? 'text-red-400' : 
                'text-text/60'
              } leading-relaxed`}>
                {log}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
