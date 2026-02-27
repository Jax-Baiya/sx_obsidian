import { supabase } from "@/lib/supabase";
import { Calendar, Plus, Clock, PlayCircle, CheckCircle2 } from "lucide-react";

export const revalidate = 0;

export default async function SchedulePage() {
  const { data: artifacts, error } = await supabase
    .schema("sx_assets_1")
    .from("scheduling_artifacts")
    .select("*")
    .order("created_at", { ascending: false });

  const safeArtifacts = artifacts || [];

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500">
      <header className="flex justify-between items-end border-b border-crust/30 pb-4">
        <div>
          <h1 className="text-4xl font-display text-mauve tracking-wider">Schedule</h1>
          <p className="text-sm font-sans text-text/60 mt-1 uppercase tracking-widest font-mono">
            Orchestration & Timing • {safeArtifacts.length} drafts
          </p>
        </div>
        <button className="flex items-center space-x-2 bg-mauve hover:bg-mauve/90 text-crust px-5 py-2.5 rounded-sm font-medium transition-colors shadow-[0_0_15px_rgba(203,166,247,0.15)] hover:shadow-[0_0_20px_rgba(203,166,247,0.3)]">
          <Calendar className="w-4 h-4" />
          <span>New Campaign</span>
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 tracking-wide">
        {safeArtifacts.map((artifact) => {
          let payload: Record<string, any> = {};
          try {
             payload = typeof artifact.artifact_json === 'string' 
              ? JSON.parse(artifact.artifact_json) 
              : artifact.artifact_json || {};
          } catch(e) {}
          
          return (
            <div
              key={`${artifact.source_id}-${artifact.video_id}-${artifact.platform}`}
              className="group relative bg-mantle border border-crust/20 hover:border-mauve/40 rounded-md overflow-hidden transition-all duration-300 shadow-sm hover:shadow-xl hover:shadow-mauve/5"
            >
              <div className="aspect-[9/16] bg-crust relative flex items-center justify-center p-4">
                {artifact.r2_media_url ? (
                  <div className="absolute inset-0 bg-gradient-to-t from-mantle to-crust opacity-80" />
                ) : (
                  <div className="absolute inset-0 bg-gradient-to-t from-mantle to-transparent opacity-80" />
                )}
                
                <PlayCircle className="w-12 h-12 text-teal/50 group-hover:text-teal transition-all duration-300 transform group-hover:scale-110 z-10" />
                <div className="absolute bottom-4 left-4 right-4 z-10">
                  <p className="text-text font-semibold truncate text-[15px]">{artifact.video_id}</p>
                  <div className="flex items-center space-x-2 mt-2 text-xs text-text/60">
                    <span className="capitalize">{artifact.platform}</span>
                    <span>•</span>
                    <span className="flex items-center text-teal">
                      <Clock className="w-3 h-3 mr-1" />
                      {artifact.status.replace("_", " ")}
                    </span>
                  </div>
                </div>
              </div>
              <div className="p-4 flex flex-col justify-between border-t border-crust/20 bg-mantle">
                <p className="text-sm text-text/80 line-clamp-2 min-h-[40px] leading-relaxed">
                  {payload?.title || payload?.caption || "No parsed content provided."}
                </p>
                
                <div className="mt-4 pt-3 border-t border-crust/20 flex justify-end space-x-3">
                  <button className="text-xs font-semibold text-text/50 hover:text-teal transition-colors p-1 uppercase tracking-wider">
                    Edit JSON
                  </button>
                  <button className="text-xs font-semibold text-text hover:text-mauve transition-colors p-1 uppercase tracking-wider flex items-center">
                    <CheckCircle2 className="w-3 h-3 mr-1"/> Approve
                  </button>
                </div>
              </div>
            </div>
          );
        })}

        {safeArtifacts.length === 0 && !error && (
          <div className="col-span-full py-20 flex flex-col items-center justify-center text-text/30 border border-dashed border-crust/40 rounded-lg bg-mantle shadow-inner">
            <Clock className="w-12 h-12 mb-4 opacity-50 text-mauve" />
            <p className="text-lg font-serif">No active schedules found.</p>
            <p className="text-sm font-sans mt-2 font-mono text-xs text-text/40">Queue items for draft review to orchestrate timing.</p>
          </div>
        )}
        
        {error && (
          <div className="col-span-full p-4 bg-red-900/20 border border-red-500/30 rounded text-red-400">
            <p className="font-semibold">Error fetching from Supabase:</p>
            <p className="text-sm mt-1">{error.message}</p>
            <p className="text-xs mt-2 text-red-400/70">Check schema name in connection.</p>
          </div>
        )}
      </div>
    </div>
  );
}
