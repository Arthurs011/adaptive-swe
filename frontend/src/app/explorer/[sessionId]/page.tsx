"use client";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import Editor from "@monaco-editor/react";
import { api } from "@/lib/api";

type Entry = { name: string; path: string; type: "dir" | "file" };
type Browse = { path: string; entries?: Entry[]; content?: string; file?: boolean };
type GNode = { id: string; type: string; file?: string; weight?: number };
type GEdge = { source: string; target: string; rel: string };
type Graph = { nodes: GNode[]; edges: GEdge[]; statistics: any };

const COLORS: Record<string, string> = {
  function: "#10b981", method: "#34d399", file: "#6366f1", module: "#6366f1",
  class: "#8b5cf6", test: "#f59e0b", test_function: "#f59e0b", "call site": "#64748b",
};

export default function ExplorerPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [path, setPath] = useState("");
  const [browse, setBrowse] = useState<Browse | null>(null);
  const [funcs, setFuncs] = useState<any[]>([]);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const go = useCallback(async (p: string) => {
    try { setBrowse(await api.browse(sessionId, p)); setPath(p); setError(null); }
    catch (e: any) { setError(e.message); }
  }, [sessionId]);

  const loadFunctions = useCallback(async () => {
    try { setFuncs((await api.functions(sessionId, term)).functions); setError(null); }
    catch (e: any) { setError(e.message); }
  }, [sessionId, term]);

  const loadGraph = useCallback(async () => {
    try { setGraph(await api.graph(sessionId)); setError(null); }
    catch (e: any) { setError(e.message); }
  }, [sessionId]);

  useEffect(() => { go("."); loadFunctions(); loadGraph(); }, [go, loadFunctions, loadGraph]);

  const nesting = useMemo(() => {
    const list = (path || "").split("/").filter(Boolean);
    let acc = "";
    return ["", ...list.map(p => { acc = acc ? `${acc}/${p}` : p; return acc; })];
  }, [path]);

  const edgesByRel = useMemo(() => {
    const m: Record<string, number> = {};
    for (const e of graph?.edges ?? []) m[e.rel] = (m[e.rel] ?? 0) + 1;
    return m;
  }, [graph]);

  return (
    <div className="flex h-[calc(100vh-3rem)] gap-4">
      {error && <div className="fixed top-4 right-4 z-50 rounded-lg border border-destructive/40 bg-background text-destructive text-xs p-3">{error}</div>}

      {/* functions index */}
      <div className="w-72 shrink-0 rounded-xl border border-border bg-card flex flex-col overflow-hidden">
        <div className="p-3 border-b border-border">
          <input value={term} onChange={e => { setTerm(e.target.value); loadFunctions(); }}
            placeholder="search symbols…" className="w-full rounded-lg bg-background border border-input px-3 py-1.5 text-sm" />
        </div>
        <div className="flex-1 overflow-y-auto text-sm">
          {funcs.map(f => (
            <button key={f.qualified} onClick={() => go(f.file)}
              className="w-full text-left px-3 py-1.5 hover:bg-secondary/50 border-b border-border/40">
              <div className="font-mono text-xs text-primary">{f.qualified}</div>
              <div className="text-[10px] text-muted-foreground">{f.file}:{f.start} · ({f.params.join(", ")})</div>
            </button>
          ))}
          {!funcs.length && <div className="p-3 text-xs text-muted-foreground">No symbols.</div>}
        </div>
      </div>

      {/* file browser + editor */}
      <div className="flex-1 min-w-0 rounded-xl border border-border bg-card flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-border flex items-center gap-1 text-xs font-mono overflow-x-auto whitespace-nowrap">
          {nesting.map((p, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-muted-foreground">/</span>}
              <button onClick={() => go(p)} className={p === (browse?.path ?? "") ? "text-primary" : "text-muted-foreground hover:text-foreground"}>{p || "root"}</button>
            </span>
          ))}
        </div>
        <div className="flex-1 min-h-0 flex">
          {browse?.entries ? (
            <div className="w-72 shrink-0 border-r border-border overflow-y-auto p-2">
              {browse.entries.map(e => (
                <button key={e.path} onClick={() => go(e.path)}
                  className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded text-sm hover:bg-secondary/50">
                  <span className="w-3">{e.type === "dir" ? "▸" : ""}</span>
                  <span className={e.type === "dir" ? "text-primary font-medium" : "font-mono text-xs"}>{e.name}</span>
                </button>
              ))}
              {!browse.entries.length && <div className="p-2 text-xs text-muted-foreground">empty</div>}
            </div>
          ) : null}
          <div className="flex-1 min-w-0">
            {browse?.content !== undefined ? (
              <Editor height="100%" defaultLanguage="python" theme="vs-dark" value={browse.content} options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13 }} />
            ) : (
              <div className="h-full flex items-center justify-center text-sm text-muted-foreground">Select a file to view its source</div>
            )}
          </div>
        </div>
      </div>

      {/* ARISE-style graph */}
      <div className="w-80 shrink-0 rounded-xl border border-border bg-card flex flex-col overflow-hidden">
        <div className="p-3 border-b border-border flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">ARISE graph</span>
          <button onClick={loadGraph} className="text-xs text-primary hover:underline">rebuild</button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {graph && (
            <>
              <div className="flex flex-wrap gap-1.5 mb-3 text-[10px] text-muted-foreground">
                {Object.entries((graph.statistics?.node_types ?? {}) as Record<string, number>).map(([t, c]) => (
                  <span key={t} className="rounded-full px-2 py-0.5" style={{ backgroundColor: `${COLORS[t] ?? "#64748b"}22`, color: COLORS[t] ?? "#64748b" }}>{t} {c}</span>
                ))}
              </div>
              <div className="space-y-px">
                {edgesByRel && Object.entries(edgesByRel).map(([rel, c]) => (
                  <div key={rel} className="flex justify-between text-[11px] text-muted-foreground"><span>{rel}</span><span>{c}×</span></div>
                ))}
              </div>
              <div className="mt-3 border-t border-border pt-3 space-y-0.5">
                {graph.nodes.slice(0, 120).map(n => (
                  <div key={n.id} className="flex items-center justify-between gap-2 text-[11px] font-mono">
                    <button onClick={() => n.file && go(n.file)} className="truncate hover:text-primary" title={n.id}>{n.id}</button>
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: COLORS[n.type] ?? "#64748b" }} />
                  </div>
                ))}
                {graph.nodes.length > 120 && <div className="text-[10px] text-muted-foreground">+ {graph.nodes.length - 120} more…</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}