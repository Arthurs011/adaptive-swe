"use client";
import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Attempt = {
  id: string; attempt: number; story?: string | null; failure_reason?: string | null;
  verified: boolean; regression_passed?: boolean; existing_passed?: boolean; existing_count: number;
  duration_s: number; tokens: number;
  patches: Array<{ content: string; files?: string; description?: string }>;
  tests: Array<{ path: string; content: string; role: string }>;
  test_results: Array<{ test: string; outcome: string; duration_ms: number; message?: string }>;
};
type Session = {
  id: string; name: string; status: string; baseline: string; use_memory: boolean;
  started_at: string | null; completed_at: string | null; result_summary: string | null;
  timeline: Array<{ step: string; message: string; detail?: string | null; at: string }>;
  attempts: Attempt[]; jobs_pending: boolean;
};

function Diff({ content }: { content: string }) {
  return (
    <pre className="text-xs leading-relaxed overflow-x-auto p-3 rounded-lg bg-background border border-border max-h-96 overflow-y-auto font-mono">
      {content.split("\n").map((line, i) => {
        let cls = "";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff-add";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff-del";
        else if (line.startsWith("@")) cls = "text-primary";
        return <div key={i} className={cls}>{line || "\u00A0"}</div>;
      })}
    </pre>
  );
}

export default function RepairWorkspace({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [s, setS] = useState<Session | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openAttempt, setOpenAttempt] = useState<number | null>(null);
  const load = useCallback(async () => {
    try { const d = await api.repair(sessionId); setS(d); setErr(null); }
    catch (e: any) { setErr(`Session unavailable: ${e.message}`); }
  }, [sessionId]);
  useEffect(() => {
    load();
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [load]);

  const statusColor = s?.status === "success" ? "bg-success/15 text-success"
    : s?.status === "failed" ? "bg-destructive/15 text-destructive"
    : "bg-warning/15 text-warning animate-pulse-slow";

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-3">
            {s?.name ?? "Loading…"}
            {s && <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColor}`}>{s.status}</span>}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            baseline: <span className="text-foreground font-mono">{s?.baseline}</span>
            {" · "}memory: <span className="text-foreground">{s?.use_memory ? "on" : "off"}</span>
            {s?.completed_at && ` · done ${new Date(s.completed_at).toLocaleTimeString()}`}
          </p>
        </div>
        {s && (
          <Link href={`/explorer/${s.id}`} className="bg-secondary px-3 py-2 rounded-lg text-sm hover:bg-secondary/70">
            Code Explorer →
          </Link>
        )}
      </div>

      {err && <div className="rounded-lg border border-destructive/40 bg-destructive/10 text-destructive text-sm p-3 mb-4">{err}</div>}
      {s?.jobs_pending && <div className="text-xs text-warning mb-4 animate-pulse-slow">● job running on backend — this page updates live</div>}

      {s?.result_summary && (
        <div className="rounded-xl border border-border bg-success/5 p-4 mb-6 text-sm text-foreground/90">
          <span className="font-semibold text-success">Result:</span> {s.result_summary}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <Section title="Timeline">
          <div className="space-y-0.5">
            {s?.timeline.map((e, i) => (
              <div key={i} className="flex gap-2 text-sm py-1 border-b border-border/40 last:border-0">
                <span className="text-muted-foreground text-xs mt-0.5 shrink-0 w-14 font-mono">{e.at.slice(11)}</span>
                <span className={`shrink-0 w-20 text-xs font-mono mt-0.5 ${
                  e.step === "repair" ? "text-warning" : e.step === "tests" ? "text-primary" :
                  e.step === "memory" ? "text-success" : "text-muted-foreground"
                }`}>{e.step}</span>
                <span>{e.message}</span>
              </div>
            ))}
            {!s?.timeline.length && <div className="text-sm text-muted-foreground">No events yet.</div>}
          </div>
        </Section>

        <Section title={`Repair attempts (${s?.attempts.length ?? 0})`}>
          <div className="space-y-3">
            {s?.attempts.map(a => (
              <div key={a.id} className="rounded-lg border border-border bg-background">
                <button onClick={() => setOpenAttempt(openAttempt === a.attempt ? null : a.attempt)}
                  className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-secondary/30">
                  <span className="font-medium text-sm">
                    Attempt {a.attempt}
                    <span className={`ml-2 px-2 py-0.5 rounded-full text-xs ${
                      a.verified ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"}`}>
                      {a.verified ? "verified ✓" : "failed"}
                    </span>
                  </span>
                  <span className="text-xs text-muted-foreground font-mono">{a.duration_s}s · {a.tokens} tok</span>
                </button>
                {openAttempt === a.attempt && (
                  <div className="px-4 pb-4 space-y-4">
                    {a.story && <p className="text-xs text-muted-foreground"><span className="text-foreground/80 font-medium">strategy: </span>{a.story}</p>}
                    {a.failure_reason && <p className="text-xs text-destructive"><span className="font-medium">why it failed: </span>{a.failure_reason}</p>}
                    <div>
                      <div className="text-xs text-muted-foreground uppercase mb-1.5">regression: {a.regression_passed ? "PASS" : "FAIL"} · existing: {a.existing_passed} of {a.existing_count} pass</div>
                      <div className="grid gap-2">
                        {a.test_results.map((r, i) => (
                          <div key={i} className="flex items-center justify-between text-xs">
                            <span className="font-mono">{r.test}</span>
                            <span className={`font-medium ${r.outcome === "passed" ? "text-success" : "text-destructive"}`}>{r.outcome}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    {a.patches.map((p, i) => (
                      <div key={i}>
                        <div className="text-xs text-muted-foreground mb-1.5">
                          patch {i + 1}{p.files ? ` · files: ${p.files}` : ""}{p.description ? ` · ${p.description}` : ""}
                        </div>
                        <Diff content={p.content} />
                      </div>
                    ))}
                    {a.tests.map((t, i) => (
                      <details key={i}>
                        <summary className="text-xs text-primary cursor-pointer">test file: {t.path}</summary>
                        <pre className="text-xs p-3 rounded-lg bg-background border border-border font-mono mt-2 overflow-x-auto">{t.content}</pre>
                      </details>
                    ))}
                    {!a.patches.length && <div className="text-xs text-muted-foreground">No patch file recorded (patch rejected/regenerated).</div>}
                  </div>
                )}
              </div>
            ))}
            {!s?.attempts.length && <div className="text-sm text-muted-foreground">No attempts yet — the pipeline is still analyzing.</div>}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground mb-3">{title}</h2>
      {children}
    </div>
  );
}