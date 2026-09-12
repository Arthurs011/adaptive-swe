"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Wrench, FlaskConical, Brain, GitCompare } from "lucide-react";

const NAV = [
  { href: "/",          label: "Dashboard",        icon: LayoutDashboard },
  { href: "/memory",    label: "Repair Memory",    icon: Brain },
  { href: "/evaluations", label: "Evaluations",    icon: GitCompare },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="flex h-screen">
      <aside className="w-60 shrink-0 border-r border-border bg-card flex flex-col gap-1 p-4">
        <div className="mb-6 px-1">
          <span className="font-bold text-primary text-lg tracking-tight">adaptive-swe</span>
          <span className="block text-xs text-muted-foreground mt-0.5">self-healing engineer</span>
        </div>
        {NAV.map(n => (
          <Link
            key={n.href}
            href={n.href}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors
              ${path === n.href ? "bg-primary/10 text-primary font-medium" : "text-muted-foreground hover:text-foreground hover:bg-secondary"}`}
          >
            <n.icon size={16} />
            {n.label}
          </Link>
        ))}
        <div className="mt-auto text-[10px] text-muted-foreground px-1">
          ARISE + AutoCodeRover
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}