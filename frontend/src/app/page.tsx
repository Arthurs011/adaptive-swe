"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Dash = {
  total_sessions: number;
  success: number;
  failed: number;
  running: number;
  success_rate: number;
  avg_attempts: number;
  memory_entries: number;
  recent: Array<{ id: string; name: string; status: string; baseline: string; use_memory: boolean; created_at: string }>;
};

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 glow">
      <div className="text-xs text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className="text-3xl font-bold mt-1 text-foreground">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<Dash | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setData(await api.dashboard()); setErr(null); }
    catch (e: any) { setErr(`Backend unreachable — start it with: uv run uvicorn app.main:app --port 8000 (${e.message})`); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Repair Dashboard</h1>
          <p className="text-sm text-muted-foreground">Autonomous repair sessions · live metrics</p>
        </div>
        <Link href="/#new"
          className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90">
          New Repair
        </Link>
      </div>

      {err && <div className="rounded-lg border border-destructive/40 bg-destructive/10 text-destructive text-sm p-3 mb-4">{err}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
        <StatCard label="Sessions" value={String(data?.total_sessions ?? "–")} />
        <StatCard label="Rates" value={`${((data?.success_rate ?? 0) * 100).toFixed(0)}%`} sub={data ? `${data.success} ok · ${data.failed} failed` : ""} />
        <StatCard label="Running" value={String(data?.running ?? "–")} sub="active jobs" />
        <StatCard label="Avg Attempts" value={String(data?.avg_attempts ?? "–")} sub="repairs / issue" />
        <StatCard label="Memory" value={String(data?.memory_entries ?? "–")} sub="learned repairs" />
      </div>

      <h2 className="text-lg font-semibold mb-3">Recent Issues</h2>
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground text-xs uppercase border-b border-border">
            <tr><th className="p-3">Issue</th><th className="p-3">Status</th><th className="p-3">Baseline</th><th className="p-3">Memory</th><th className="p-3">Created</th></tr>
          </thead>
          <tbody>
            {(data?.recent ?? []).map(r => (
              <tr key={r.id} className="border-b border-border/50 last:border-0 hover:bg-secondary/40">
                <td className="p-3">
                  <Link href={`/repair/${r.id}`} className="font-medium hover:text-primary">{r.name}</Link>
                </td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${
                    r.status === "success" ? "bg-success/15 text-success"
                    : r.status === "failed" ? "bg-destructive/15 text-destructive"
                    : "bg-warning/15 text-warning animate-pulse-slow"
                  }`}>{r.status}</span>
                </td>
                <td className="p-3 text-muted-foreground">{r.baseline}</td>
                <td className="p-3">{r.use_memory ? "✓" : "—"}</td>
                <td className="p-3 text-muted-foreground">{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {!data?.recent?.length && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">No issues yet — create a repair and watch it work.</td></tr>}
          </tbody>
        </table>
      </div>

      <div id="new" className="mt-8 rounded-xl border border-border bg-card p-5">
        <h2 className="font-semibold mb-3">Start a Repair Job</h2>
        <a href="/repair/new" className="inline-flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90">
          Create repair job
        </a>
        <p className="text-xs text-muted-foreground mt-2">Enter repository URL (GitHub or local path) and a bug report. The pipeline clones, analyzes, patches, tests and stores the repair.</p>
      </div>
    </div>
  );
}