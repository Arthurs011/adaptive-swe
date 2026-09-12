const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  dashboard:      ()                  => request<any>("/api/dashboard"),
  startRepair:    (body: any)         => request<any>("/api/repair", { method: "POST", body: JSON.stringify(body) }),
  repair:         (id: string)        => request<any>(`/api/repair/${id}`),
  graph:          (id: string)        => request<any>(`/api/repair/${id}/graph`, { method: "POST" }),
  browse:         (id: string, path: string) => request<any>(`/api/repo/${id}/browse?path=${encodeURIComponent(path)}`),
  functions:      (id: string, term: string) => request<any>(`/api/repo/${id}/functions?term=${encodeURIComponent(term)}`),
  memory:         ()                  => request<any>("/api/memory"),
  deleteMemory:   (id: string)        => request(`/api/memory/${id}`, { method: "DELETE" as const }),
  evaluate:       (body: any)         => request<any>("/api/evaluate", { method: "POST", body: JSON.stringify(body) }),
  evaluations:    ()                  => request<any>("/api/evaluations"),
  comparison:     ()                  => request<any>("/api/comparison"),
};