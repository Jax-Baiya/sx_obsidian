import { supabase } from "@/lib/supabase";
import { Clock, PlayCircle, Plus, Library } from "lucide-react";
import { LibraryTabs } from "@/components/LibraryTabs";
import { Suspense } from "react";

export const revalidate = 0; // Disable static caching for local control plane

type Props = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}

export default async function LibraryPage(props: Props) {
  // Await search params in Next.js 15
  const searchParams = await props.searchParams;
  const activeProfile = typeof searchParams.profile === 'string' ? searchParams.profile : 'sx_assets_1';

  // Try fetching from the active profile schema
  const { data: videos, error } = await supabase
    .schema(activeProfile) 
    .from("videos")
    .select("id, platform, caption, updated_at")
    .order("updated_at", { ascending: false })
    .limit(20);

  const safeVideos = videos || [];

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500">
      <header className="flex justify-between items-end border-b border-crust/30 pb-4">
        <div>
          <h1 className="text-4xl font-display text-mauve tracking-wider">Library</h1>
          <p className="text-sm font-sans text-text/60 mt-1 uppercase tracking-widest font-mono">
            {activeProfile.replace('sx_assets_', 'Profile ')} • {safeVideos.length} items
          </p>
        </div>
        <button className="flex items-center space-x-2 bg-mauve hover:bg-mauve/90 text-crust px-5 py-2.5 rounded-sm font-medium transition-colors shadow-[0_0_15px_rgba(203,166,247,0.15)] hover:shadow-[0_0_20px_rgba(203,166,247,0.3)]">
          <Plus className="w-4 h-4" />
          <span>New Scheduled Job</span>
        </button>
      </header>

      {/* Tab Navigation Client Component */}
      <Suspense fallback={<div className="h-[45px] w-full animate-pulse bg-crust/50 rounded-md mb-8"></div>}>
        <LibraryTabs />
      </Suspense>

      {/* Media Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 tracking-wide">
        {safeVideos.map((video) => (
          <div
            key={video.id}
            className="group relative bg-mantle border border-crust/20 hover:border-mauve/40 rounded-md overflow-hidden transition-all duration-300 shadow-sm hover:shadow-xl hover:shadow-mauve/5"
          >
            <div className="aspect-[9/16] bg-crust relative flex items-center justify-center p-4">
              {/* Fallback visual for video cover */}
              <div className="absolute inset-0 bg-gradient-to-t from-mantle to-transparent opacity-80" />
              <PlayCircle className="w-12 h-12 text-teal/50 group-hover:text-teal transition-all duration-300 transform group-hover:scale-110 z-10" />
              <div className="absolute bottom-4 left-4 right-4 z-10">
                <p className="text-text font-semibold truncate text-[15px]">{video.id}</p>
                <div className="flex items-center space-x-2 mt-2 text-xs text-text/60">
                  <span className="capitalize">{video.platform || "tiktok"}</span>
                  <span>•</span>
                  <span className="flex items-center text-teal">
                    <Clock className="w-3 h-3 mr-1" />
                    {new Date(video.updated_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            </div>
            <div className="p-4 flex flex-col justify-between border-t border-crust/20 bg-mantle">
              <p className="text-sm text-text/80 line-clamp-2 min-h-[40px] leading-relaxed">
                {video.caption || "No caption provided."}
              </p>
              
              <div className="mt-4 pt-3 border-t border-crust/20 flex justify-end space-x-3">
                <button className="text-xs font-semibold text-text/50 hover:text-teal transition-colors p-1 uppercase tracking-wider">
                  Edit
                </button>
                <button className="text-xs font-semibold text-text hover:text-mauve transition-colors p-1 uppercase tracking-wider">
                  Schedule
                </button>
              </div>
            </div>
          </div>
        ))}

        {safeVideos.length === 0 && !error && (
          <div className="col-span-full py-20 flex flex-col items-center justify-center text-text/30 border border-dashed border-crust/40 rounded-lg bg-mantle shadow-inner">
            <Library className="w-12 h-12 mb-4 opacity-50 text-mauve" />
            <p className="text-lg font-serif">Library is empty.</p>
            <p className="text-sm font-sans mt-2 font-mono text-xs text-text/40">Connect a source to import media.</p>
          </div>
        )}
        
        {error && (
          <div className="col-span-full p-6 bg-crust border border-red-500/30 rounded-lg text-red-400">
            <p className="font-semibold mb-2">Supabase Error</p>
            <p className="text-sm text-red-300 font-mono p-3 bg-mantle rounded mb-4 overflow-x-auto whitespace-pre-wrap">{error.message}</p>
            {error.code === 'PGRST106' && (
              <p className="text-sm text-text/60">
                The schema `<span className="font-mono text-mauve">{activeProfile}</span>` does not exist in the connected database. 
                Are you sure you mirrored this vaulted profile to Supabase?
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
