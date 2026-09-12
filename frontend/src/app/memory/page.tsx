"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type MemEntry = {
  id: string; repository_url: string; issue_category?: string; issue_description?: string;
  affected_files?: string; affected_functions?: string; fault_pattern?: string; solution_pattern?: string;
  successful?: boolean; num_attempts?: number; usage_count?: number; created_at?: string;
  failure_reasons?: string; generated_patch?: string;
};

export default function MemoryPage() {
  const [entries, setEntries] = useState<MemEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setEntries((await api.memory()).entries); setError(null); }
    catch (e: any) { setError(e.message); }
  }, []);
  const del = async (id: string) => {
    await api.deleteMemory(id);
    setEntries(entries.filter(e => e.id !== id));
  };
  useEffect(() => { load(); }, [load]);

  return (
    <div className="max-w-6xl">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Repair Memory</h1>
          <p className="text-sm text-muted-foreground">Persistent, repository-specific repair knowledge — retrieved on future similar issues.</p>
        </div>
        <span className="text-sm text-muted-foreground">{entries.length} stored</span>
      </div>
      {error && <div className="rounded-lg border border-destructive/40 bg-destructive/10 text-destructive text-sm p-3 mb-4">{error}</div>}
      <div className="grid md:grid-cols-2 gap-4">
        {entries.map(e => (
          <div key={e.id} className="rounded-xl border border-border bg-card p-4 glow">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-mono rounded-full bg-secondary px-2 py-0.5">{e.repository_url}</span>
              <div className="flex gap-2">
                {e.successful !== undefined && (
                  <span className={`text-xs rounded-full px-2 py-0.5 ${e.successful ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"}`}>
                    {e.successful ? "success" : "couldn't fix"}
                  </span>
                )}
                <button onClick={() => del(e.id)} className="text-xs text-muted-foreground hover:text-destructive">delete</button>
              </div>
            </div>
            <h3 className="font-medium text-sm">{e.issue_category || "uncategorized issue"}</h3>
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{e.issue_description}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div><span className="text-muted-foreground">files: </span>{e.affected_files || "–"}</div>
              <div><span className="text-muted-foreground">functions: </span>{e.affected_functions || "–"}</div>
              <div><span className="text-muted-foreground">fault: </span>{e.fault_pattern || "–"}</div>
              <div><span className="text-muted-foreground">solution: </span>{e.solution_pattern || "–"}</div>
            </div>
            <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground border-t border-border pt-2">
              <span>{e.num_attempts ?? 0} attempts</span>
              <span>used {e.usage_count ?? 0}×</span>
              {e.created_at && <span className="ml-auto font-mono">{e.created_at.slice(0, 16)}</span>}
            </div>
            {e.generated_patch && (
              <details className="mt-2">
                <summary className="text-xs text-primary cursor-pointer">stored patch</summary>
                <pre className="text-[10px] p-2 mt-2 rounded bg-background border border-border font-mono overflow-x-auto max-h-48 overflow-y-auto">{e.generated_patch}</pre>
              </details>
            )}
          </div>
        ))}
        {!entries.length && <div className="col-span-full text-sm text-muted-foreground">No repair memory yet — repaired issues are stored here automatically.</div>}
      </div>
    </div>
  );
}