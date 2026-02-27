import { supabase } from "@/lib/supabase";
import { CheckCircle2, CircleDashed, AlertCircle, PlayCircle, RefreshCw } from "lucide-react";

export const revalidate = 0;

export default async function QueuePage() {
  const { data: jobs, error } = await supabase
    .schema("sx_assets_1") // Assuming profile 1 schema
    .from("job_queue")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(50);

  const safeJobs = jobs || [];

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500">
      <header className="flex justify-between items-end border-b border-crust/30 pb-4">
        <div>
          <h1 className="text-4xl font-display text-mauve tracking-wider">Job Queue</h1>
          <p className="text-sm font-sans text-text/60 mt-1 uppercase tracking-widest font-mono">
            Publishing Pipeline
          </p>
        </div>
        <button className="flex items-center space-x-2 text-text/70 hover:text-mauve transition-colors">
          <RefreshCw className="w-4 h-4" />
          <span className="text-sm font-medium uppercase tracking-wider">Refresh</span>
        </button>
      </header>

      <div className="bg-mantle border border-crust/20 rounded-md overflow-hidden shadow-sm">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-crust/40 border-b border-crust/20 text-text/50 text-xs uppercase tracking-wider font-mono">
              <th className="py-4 px-6 font-medium">Status</th>
              <th className="py-4 px-6 font-medium">Video ID</th>
              <th className="py-4 px-6 font-medium">Platform</th>
              <th className="py-4 px-6 font-medium">Action</th>
              <th className="py-4 px-6 font-medium text-right">Created At</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {safeJobs.map((job) => (
              <tr key={job.id} className="border-b border-crust/10 last:border-0 hover:bg-crust/20 transition-colors">
                <td className="py-4 px-6">
                  <div className="flex items-center space-x-2">
                    {job.status === "completed" && <CheckCircle2 className="w-4 h-4 text-teal" />}
                    {job.status === "pending" && <CircleDashed className="w-4 h-4 text-text/40 animate-spin-slow" />}
                    {job.status === "processing" && <PlayCircle className="w-4 h-4 text-mauve animate-pulse" />}
                    {job.status === "failed" && <AlertCircle className="w-4 h-4 text-red-500" />}
                    <span className={`capitalize ${job.status === "failed" ? "text-red-400 font-medium" : "text-text"}`}>
                      {job.status}
                    </span>
                  </div>
                </td>
                <td className="py-4 px-6 font-mono text-text/80">{job.video_id}</td>
                <td className="py-4 px-6 capitalize text-text">{job.platform}</td>
                <td className="py-4 px-6 text-text/60">{job.action}</td>
                <td className="py-4 px-6 text-right text-text/50 font-mono text-xs">
                  {new Date(job.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
            
            {safeJobs.length === 0 && !error && (
              <tr>
                <td colSpan={5} className="py-12 text-center text-text/40">
                  <p className="font-serif text-lg text-text/60">Queue is empty</p>
                  <p className="font-sans text-sm mt-1 font-mono text-xs">No jobs have been enqueued yet.</p>
                </td>
              </tr>
            )}
            
            {error && (
              <tr>
                <td colSpan={5} className="py-8 px-6 text-center text-red-400 bg-red-900/10">
                  <p>Error loading queue: {error.message}</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
