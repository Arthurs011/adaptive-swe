"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function NewRepairPage() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [baseline, setBaseline] = useState("proposed");
  const [useMemory, setUseMemory] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api.startRepair({ repo_url: repoUrl, title, description, baseline, use_memory: useMemory });
      router.push(`/repair/${res.session_id}`);
    } catch (e: any) {
      setError(e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Start a Repair Job</h1>
      <div className="rounded-xl border border-border bg-card p-6 space-y-4">
        <Field label="Repository">
          <input value={repoUrl} onChange={e => setRepoUrl(e.target.value)} placeholder="git@github.com:org/repo.git  or  /path/to/local/repo"
            className="w-full rounded-lg bg-background border border-input px-3 py-2 text-sm" />
          <p className="text-xs text-muted-foreground mt-1">GitHub URL or a local git repo path. Python repos supported in the MVP.</p>
        </Field>
        <Field label="Bug report title">
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Empty CSV causes server error"
            className="w-full rounded-lg bg-background border border-input px-3 py-2 text-sm" />
        </Field>
        <Field label="Bug description">
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={5}
            placeholder="Describe the failing behaviour, expected behaviour, and any hints..."
            className="w-full rounded-lg bg-background border border-input px-3 py-2 text-sm" />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Repair algorithm">
            <select value={baseline} onChange={e => setBaseline(e.target.value)} className="w-full rounded-lg bg-background border border-input px-3 py-2 text-sm">
              <option value="baseline1">baseline1 — plain LLM</option>
              <option value="baseline2">baseline2 — ARISE-style (graph)</option>
              <option value="proposed">proposed — graph + memory + adaptation</option>
            </select>
          </Field>
          <Field label="Repair memory">
            <select value={String(useMemory)} onChange={e => setUseMemory(e.target.value === "true")} className="w-full rounded-lg bg-background border border-input px-3 py-2 text-sm">
              <option value="true">Use persistent memory</option>
              <option value="false">Do not use memory</option>
            </select>
          </Field>
        </div>
        {error && <div className="text-destructive text-sm">{error}</div>}
        <button onClick={submit} disabled={busy || !repoUrl || !title}
          className="w-full bg-primary text-primary-foreground rounded-lg py-2.5 font-medium hover:opacity-90 disabled:opacity-50">
          {busy ? "Starting…" : "Run Repair"}
        </button>
        <p className="text-xs text-muted-foreground">The job runs on the backend (clone → analysis → ARISE graph → localization → regression test → patch loop → sandbox execution → memory store).</p>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block">
    <span className="text-xs text-muted-foreground uppercase tracking-wide block mb-1.5">{label}</span>
    {children}
  </label>;
}