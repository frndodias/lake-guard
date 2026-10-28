import type {
  AgentResult, Alert, AlertPage, AlertStats, AlertStatus, Capability, ChatMessage, ChatResponse,
  Conversation, EffectivePermission, GenieAnswer, Grant, Me, NLResult, Severity, User, Workspace,
} from "./types";

/** Query string ignorando valores vazios. */
function qs(params: Record<string, string | number | undefined | null>): string {
  const e = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? `?${new URLSearchParams(e.map(([k, v]) => [k, String(v)])).toString()}` : "";
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => req<Me>("/api/me"),

  users: (search?: string) =>
    req<User[]>(`/api/users${search ? `?search=${encodeURIComponent(search)}` : ""}`),

  capabilities: () => req<Capability[]>("/api/capabilities"),
  patchCapability: (code: string, body: { enabled?: boolean; default_severity?: Severity }) =>
    req<Capability>(`/api/capabilities/${code}`, { method: "PATCH", body: JSON.stringify(body) }),

  grants: (principal?: string, workspaceId?: string) =>
    req<Grant[]>(`/api/grants${qs({ principal, workspace_id: workspaceId })}`),
  upsertGrant: (body: {
    principal: string; principal_type: string; capability: string; workspace_id: string; allowed: boolean;
  }) => req<Grant>("/api/grants", { method: "POST", body: JSON.stringify(body) }),
  deleteGrant: (id: number) => req<{ deleted: number }>(`/api/grants/${id}`, { method: "DELETE" }),
  effective: (email: string, workspaceId?: string) =>
    req<{ email: string; groups: string[]; permissions: EffectivePermission[] }>(
      `/api/grants/effective/${encodeURIComponent(email)}${qs({ workspace_id: workspaceId })}`,
    ),

  workspaces: () => req<{ app_workspace_id: string; workspaces: Workspace[] }>("/api/workspaces"),

  alerts: (params: {
    status?: string; severity?: string; principal?: string; workspace_id?: string;
    limit?: number; offset?: number;
  } = {}) => req<AlertPage>(`/api/alerts${qs(params)}`),
  alertStats: (workspaceId?: string) =>
    req<AlertStats>(`/api/alerts/stats${qs({ workspace_id: workspaceId })}`),
  patchAlert: (id: number, body: { status: AlertStatus; notes?: string }) =>
    req<Alert>(`/api/alerts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remediate: (id: number) =>
    req<{ ok: boolean; detail: string }>(`/api/alerts/${id}/remediate`, { method: "POST" }),

  allowedForMe: () =>
    req<{ email: string; groups: string[]; permissions: (EffectivePermission & { supported?: boolean })[] }>(
      "/api/assets/allowed",
    ),
  createAssetNL: (prompt: string) =>
    req<NLResult>("/api/assets/nl", { method: "POST", body: JSON.stringify({ prompt }) }),
  agent: (prompt: string) =>
    req<AgentResult>("/api/agent", { method: "POST", body: JSON.stringify({ prompt }) }),

  conversations: () => req<Conversation[]>("/api/conversations"),
  conversation: (id: number) =>
    req<{ conversation: Conversation; messages: ChatMessage[] }>(`/api/conversations/${id}`),
  deleteConversation: (id: number) =>
    req<{ deleted: number }>(`/api/conversations/${id}`, { method: "DELETE" }),
  renameConversation: (id: number, title: string) =>
    req<{ id: number; title: string }>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  chat: (prompt: string, conversationId?: number) =>
    req<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ prompt, conversation_id: conversationId ?? null }),
    }),

  detectionStatus: () =>
    req<{
      job_configured: boolean;
      state: { last_event_time: string | null; last_run_at: string | null; last_run_status: string | null; last_error: string | null } | null;
    }>("/api/detection/status"),
  runDetection: () => req<{ run_id: number }>("/api/detection/run", { method: "POST" }),

  genieStatus: () => req<{ configured: boolean; space_id: string | null }>("/api/genie/status"),
  genieAsk: (question: string, conversation_id?: string) =>
    req<GenieAnswer>("/api/genie/ask", {
      method: "POST", body: JSON.stringify({ question, conversation_id }),
    }),
};
