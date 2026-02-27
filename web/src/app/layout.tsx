import type { Metadata } from "next";
import { Inter, Playfair_Display, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { Navigation } from "@/components/Navigation";
import { ThemeProvider } from "@/components/ThemeProvider";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
});

const space = Space_Grotesk({
  variable: "--font-space",
  subsets: ["latin"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "SX Obsidian | Web Control Plane",
  description: "Cinematic web control plane for managing scheduling artifacts and publish workflows.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${inter.variable} ${space.variable} ${playfair.variable} ${jetbrains.variable} antialiased font-sans bg-background text-foreground transition-colors duration-500`}
      >
        <ThemeProvider>
          <Navigation />
          <main className="ml-64 p-8 min-h-screen">
            {children}
          </main>
        </ThemeProvider>
      </body>
    </html>
  );
}
