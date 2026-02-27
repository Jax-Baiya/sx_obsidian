import Link from "next/link";
import { Terminal, Calendar, Library, Settings, CloudUpload } from "lucide-react";

export function Navigation() {
  return (
    <nav className="fixed inset-y-0 left-0 w-64 bg-mantle border-r border-crust/20 flex flex-col pt-8 pb-4 px-4 z-50">
      <div className="flex items-center space-x-3 mb-10 px-2">
        <Terminal className="w-6 h-6 text-mauve" />
        <h1 className="text-xl font-serif text-text tracking-wide">SX Obsidian</h1>
      </div>
      
      <div className="flex-1 space-y-2">
        <NavItem href="/" icon={<Library />} label="Library" />
        <NavItem href="/queue" icon={<CloudUpload />} label="Job Queue" />
        <NavItem href="/schedule" icon={<Calendar />} label="Schedule" />
        <NavItem href="/cli" icon={<Terminal />} label="Web CLI" />
      </div>
      
      <div className="mt-auto">
        <NavItem href="/settings" icon={<Settings />} label="Settings" />
      </div>
    </nav>
  );
}

function NavItem({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <Link 
      href={href}
      className="flex items-center space-x-3 px-3 py-2.5 rounded-md text-text/70 hover:text-mauve hover:bg-crust/40 transition-colors duration-200 group"
    >
      <span className="group-hover:text-mauve transition-colors">{icon}</span>
      <span className="font-sans font-medium text-sm tracking-wide">{label}</span>
    </Link>
  );
}
