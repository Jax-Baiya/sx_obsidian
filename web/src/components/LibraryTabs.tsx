"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Layers } from "lucide-react";

const PROFILES = [
  { id: "sx_assets_1", label: "Profile 1" },
  { id: "sx_assets_2", label: "Profile 2" },
  { id: "sx_assets_3", label: "Profile 3" },
];

export function LibraryTabs() {
  const searchParams = useSearchParams();
  const currentProfile = searchParams.get("profile") || "sx_assets_1";

  return (
    <div className="flex space-x-2 border-b border-crust/30 mb-8 pt-2">
      <div className="flex items-center space-x-2 px-4 py-2 text-text/50 font-mono text-sm uppercase tracking-wider">
        <Layers className="w-4 h-4" />
        <span>Vaults</span>
      </div>
      
      {PROFILES.map((profile) => {
        const isActive = currentProfile === profile.id;
        
        return (
          <Link
            key={profile.id}
            href={`/?profile=${profile.id}`}
            className={`
              px-6 py-2.5 text-sm font-medium transition-all duration-300 relative
              ${isActive ? "text-mauve" : "text-text/60 hover:text-text hover:bg-mantle/50"}
            `}
          >
            {profile.label}
            {isActive && (
              <span className="absolute bottom-0 left-0 w-full h-[2px] bg-mauve shadow-[0_0_8px_rgba(203,166,247,0.8)]" />
            )}
          </Link>
        );
      })}
    </div>
  );
}
