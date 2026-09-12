"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Run = { id: string; name: string; baseline: string; use_memory: boolean; metrics: any; started_at: string; completed_at: string | null };
type Comparison = { available: boolean; message?: string; no_memory?: any; with_memory?: any; benefit?: any };

function MetricGrid({ label, m }: { label: string; m: any }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground uppercase mb-3">{label}</div>
      <div className="space-y-1.5 text-sm">
        <Row k="success rate" v={`${((m?.success_rate ?? 0) * 100).toFixed(0)}%`} />
        <Row k="pass@1" v={`${((m?.pass_at_1 ?? 0) * 100).toFixed(0)}%`} />
        <Row k="avg attempts" v={m?.avg_attempts ?? "–"} />
        <Row k="avg tokens" v={m?.avg_tokens ?? "–"} />
        <Row k="regression fails" v={m?.regression_failures_total ?? "–"} />
        <Row k="duration avg" v={m?.avg_duration_s ? `${m.avg_duration_s.toFixed(1)}s` : "–"} />
      </div>
    </div>
  );
}
function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex items-center justify-between"><span className="text-muted-foreground">{k}</span><span className="font-medium">{v}</span></div>;
}

export default function EvaluationsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [baseline, setBaseline] = useState("proposed");
  const [useMemory, setUseMemory] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([api.evaluations(), api.comparison()]);
      setRuns(r); setCmp(c); setError(null);
    } catch (e: any) { setError(e.message); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      await api.evaluate({ baseline, use_memory: useMemory, limit: 4 });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Evaluations & Comparison</h1>
          <p className="text-sm text-muted-foreground">Honest A/B experiment: same issue set, memory on vs off.</p>
        </div>
        <div className="flex items-center gap-3">
          <select value={baseline} onChange={e => setBaseline(e.target.value)} className="rounded-lg bg-background border border-input px-3 py-2 text-sm">
            <option value="baseline1">baseline1 (plain)</option>
            <option value="baseline2">baseline2 (graph)</option>
            <option value="proposed">proposed</option>
          </select>
          <button onClick={() => setUseMemory(!useMemory)}
            className={`px-3 py-2 rounded-lg text-sm border ${useMemory ? "border-primary text-primary" : "border-input text-muted-foreground"}`}>
            memory: {useMemory ? "on" : "off"}
          </button>
          <button onClick={run} disabled={busy} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50">
            {busy ? "Running 4 issues…" : "Run benchmark"}
          </button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-destructive/40 bg-destructive/10 text-destructive text-sm p-3 mb-4">{error}</div>}

      {cmp?.available ? (
        <div className="grid md:grid-cols-3 gap-4 mb-8">
          <MetricGrid label="No memory" m={cmp.no_memory} />
          <MetricGrid label="With memory" m={cmp.with_memory} />
          <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
            <div className="text-xs uppercase text-primary mb-3">memory benefit</div>
            {cmp.benefit && (
              <div className="space-y-1.5 text-sm">
                <Row k="Δ attempts" v={fmt(cmp.benefit.avg_attempts_delta)} />
                <Row k="Δ pass@1" v={fmt(cmp.benefit.pass_at_1_delta)} />
                <Row k="Δ success rate" v={fmt(cmp.benefit.success_rate_delta)} />
                <Row k="Δ regression fails" v={fmt(cmp.benefit.regression_failures_delta)} />
                <Row k="Δ duration" v={fmt(cmp.benefit.avg_duration_delta_s)} />
                <Row k="Δ tokens" v={fmt(cmp.benefit.avg_tokens_delta)} />
                <div className={`mt-2 pt-2 border-t border-border/50 text-xs font-medium ${(cmp.benefit.avg_attempts_delta ?? 0) < 0 || ((cmp.benefit.success_rate_delta ?? 0) > 0) ? "text-success" : "text-muted-foreground"}`}>
                  {cmp.benefit.conclusion}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground mb-8">Run one benchmark with memory on and one with memory off to see the comparison.</div>
      )}

      <h2 className="text-lg font-semibold mb-3">Recent runs</h2>
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground uppercase border-b border-border">
            <tr><th className="p-3">Run</th><th className="p-3">Baseline</th><th className="p-3">Memory</th><th className="p-3">Success</th><th className="p-3">Pass@1</th><th className="p-3">Attempts</th><th className="p-3">Started</th></tr>
          </thead>
          <tbody>
            {runs.map(r => (
              <tr key={r.id} className="border-b border-border/50">
                <td className="p-3 font-medium">{r.name}</td>
                <td className="p-3 text-muted-foreground">{r.baseline}</td>
                <td className="p-3">{r.use_memory ? "on" : "off"}</td>
                <td className="p-3">{((r.metrics?.success_rate ?? 0) * 100).toFixed(0)}%</td>
                <td className="p-3">{(r.metrics?.pass_at_1 ?? 0).toFixed(0)}/4</td>
                <td className="p-3">{r.metrics?.avg_attempts ?? "–"}</td>
                <td className="p-3 text-muted-foreground">{new Date(r.started_at).toLocaleString()}</td>
              </tr>
            ))}
            {!runs.length && <tr><td colSpan={7} className="p-6 text-center text-muted-foreground">No evaluation runs yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function fmt(v: any): string {
  if (v === undefined || v === null) return "–";
  if (typeof v === "number") return (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2));
  return String(v);
}