import { NavLink } from "react-router-dom";
import { Download, FolderOpen, History, Settings, Youtube } from "lucide-react";

const items = [
  { to: "/", label: "Dashboard", icon: Download, end: true },
  { to: "/library", label: "Library", icon: FolderOpen },
  { to: "/history", label: "History", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];

function classNames({ isActive }: { isActive: boolean }): string {
  return [
    "flex items-center justify-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors md:justify-start",
    isActive
      ? "bg-brand/15 text-brand-hover"
      : "text-fg-secondary hover:bg-surface-2 hover:text-fg",
  ].join(" ");
}

export default function Sidebar() {
  return (
    <aside className="flex w-14 shrink-0 flex-col border-r border-line bg-surface-0 md:w-[220px]">
      <div className="flex items-center justify-center gap-2.5 px-3 py-5 md:justify-start md:px-5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-on-brand">
          <Youtube className="h-5 w-5" />
        </div>
        <span className="hidden text-base font-semibold tracking-tight text-fg md:inline">
          vidfetch
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-2 md:px-3">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={classNames}
            title={item.label}
            aria-label={item.label}
          >
            <item.icon className="h-4 w-4 shrink-0" />
            <span className="hidden md:inline">{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="hidden px-5 py-4 text-xs text-fg-muted md:block">
        Powered by yt-dlp
      </div>
    </aside>
  );
}
