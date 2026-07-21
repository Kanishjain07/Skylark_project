// API base: uses Vite proxy (/api) in dev; override with VITE_API_BASE in prod.
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function postJSON(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${text || res.statusText}`);
  }
  return res.json();
}

export function sendChat(messages) {
  return postJSON("/chat", { messages });
}

export function generateLeadershipUpdate() {
  return postJSON("/leadership-update");
}

export async function getHealth() {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed (${res.status})`);
  return res.json();
}
