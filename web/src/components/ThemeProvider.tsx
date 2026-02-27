"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { useEffect } from "react";

type ThemePreset = "catppuccin" | "midnight-luxe" | "light";

interface ThemeState {
  theme: ThemePreset;
  setTheme: (theme: ThemePreset) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "catppuccin", // Default Dev Noir
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: "sx-obsidian-theme-storage",
    }
  )
);

/**
 * Client component that watches the Zustand store and injects `data-theme` into the HTML `<body>`.
 * Place this inside the root layout before other content.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((state) => state.theme);

  useEffect(() => {
    // Inject the theme variable as a data attribute into the body so CSS root overrides take over
    document.body.setAttribute("data-theme", theme);
  }, [theme]);

  // Initial load hydration safety check can go here if SSR mismatch occurs, 
  // but for raw CSS variable swaps this usually paints fast enough.
  return <>{children}</>;
}
