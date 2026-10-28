import type {
  AlertList, AssetDetail, AssetNode, ChangeRequest, DomainList, GraphData, IdentityDetail, IdentityRow, Me,
  MigrationGroups, Overview, PersonaDetail, PersonaMeta, PersonaRow, Preview, RequestTargets, Wave, WavePreview,
} from "./types";

/** Query string ignorando valores vazios. */
export function qs(params: Record<string, string | number | undefined | null>): string {
  const e = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? `?${new URLSearchParams(e.map(([k, v]) => [k, String(v)])).toString()}` : "";
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

const post = <T,>(url: string, body?: unknown) =>
  req<T>(url, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T,>(url: string, body: unknown) => req<T>(url, { method: "PUT", body: JSON.stringify(body) });
const patch = <T,>(url: string, body: unknown) => req<T>(url, { method: "PATCH", body: JSON.stringify(body) });
const del = <T,>(url: string) => req<T>(url, { method: "DELETE" });

export type GrantRowIn = { catalog: string; schema_scope: string | null; privileges: string[] };

export const api = {
  me: () => req<Me>("/api/me"),
  overview: () => req<Overview>("/api/overview"),

  identities: (type?: string, q?: string) => req<IdentityRow[]>(`/api/identities${qs({ type, q })}`),
  identity: (id: string) => req<IdentityDetail>(`/api/identities/${encodeURIComponent(id)}`),
  myAccess: () => req<IdentityDetail & { in_inventory: boolean; id?: string; email?: string }>("/api/me/access"),
  assets: () => req<AssetNode[]>("/api/assets"),
  asset: (name: string) => req<AssetDetail>(`/api/assets/detail${qs({ name })}`),
  graph: (id: string) => req<GraphData>(`/api/graph${qs({ id })}`),

  personas: () => req<PersonaRow[]>("/api/personas"),
  personaMeta: () => req<PersonaMeta>("/api/personas/meta"),
  persona: (code: string) => req<PersonaDetail>(`/api/personas/${code}`),
  personaPreview: (code: string, body: { grants?: GrantRowIn[]; capabilities?: string[]; description?: string }) =>
    post<Preview>(`/api/personas/${code}/preview`, body),
  personaPropose: (code: string, body: {
    grants?: GrantRowIn[]; capabilities?: string[]; description?: string; justification?: string;
  }) => post<ChangeRequest>(`/api/personas/${code}/propose`, body),
  personaFixGap: (code: string) => post<ChangeRequest>(`/api/personas/${code}/fix-gap`),
  personaScript: (code: string) => req<string>(`/api/personas/${code}/script`),
  personaAddMember: (code: string, body: { member_id: string; justification: string; duration_days?: number | null }) =>
    post<ChangeRequest>(`/api/personas/${code}/members`, body),
  personaRemoveMember: (code: string, memberId: string) =>
    post<ChangeRequest>(`/api/personas/${code}/members/${encodeURIComponent(memberId)}/remove`),
  personaRollback: (code: string, version: number) => post<ChangeRequest>(`/api/personas/${code}/rollback/${version}`),

  domains: () => req<DomainList>("/api/domains"),
  saveDomain: (body: Record<string, unknown>) => post("/api/domains", body),
  applyClearance: (code: string) => post<ChangeRequest>(`/api/domains/${code}/apply-clearance`),
  addSteward: (code: string, principal: string) => post(`/api/domains/${code}/stewards`, { principal }),
  removeSteward: (code: string, principal: string) =>
    del(`/api/domains/${code}/stewards/${encodeURIComponent(principal)}`),

  requests: (scope: string, status?: string) => req<ChangeRequest[]>(`/api/requests${qs({ scope, status })}`),
  request: (id: number) => req<ChangeRequest>(`/api/requests/${id}`),
  requestTargets: () => req<RequestTargets>("/api/requests/targets"),
  requestAccess: (body: {
    target_type: string; target: string; member_id?: string | null; duration_days: number; justification: string;
  }) => post<ChangeRequest>("/api/requests/access", body),
  approve: (id: number, note?: string) => post<ChangeRequest>(`/api/requests/${id}/approve`, { note }),
  reject: (id: number, note?: string) => post<ChangeRequest>(`/api/requests/${id}/reject`, { note }),
  cancel: (id: number) => post<ChangeRequest>(`/api/requests/${id}/cancel`),
  revoke: (id: number) => post<ChangeRequest>(`/api/requests/${id}/revoke`),
  expire: () => post<{ expired: number }>("/api/requests/expire"),

  migrationGroups: () => req<MigrationGroups>("/api/migration/groups"),
  setMapping: (group: string, action: string, target: string | null) =>
    put(`/api/migration/mappings/${encodeURIComponent(group)}`, { action, target }),
  waves: () => req<Wave[]>("/api/migration/waves"),
  createWave: (name: string, groups: string[]) => post<Wave>("/api/migration/waves", { name, groups }),
  deleteWave: (id: number) => del(`/api/migration/waves/${id}`),
  wavePreview: (id: number) => req<WavePreview>(`/api/migration/waves/${id}/preview`),
  submitWave: (id: number) => post<ChangeRequest>(`/api/migration/waves/${id}/submit`),
  rollbackWave: (id: number) => post<ChangeRequest>(`/api/migration/waves/${id}/rollback`),

  alerts: (status?: string, severity?: string, rule?: string) =>
    req<AlertList>(`/api/alerts${qs({ status, severity, rule })}`),
  setAlert: (id: number, status: string) => patch(`/api/alerts/${id}`, { status }),
  fixAlert: (id: number) => post<ChangeRequest>(`/api/alerts/${id}/fix`),
  evaluate: () => post<{ open: number }>("/api/admin/rules/evaluate"),

  roles: () => req<{ id: number; principal: string; principal_type: string; role: string; domain: string | null;
    granted_by: string; granted_at: string }[]>("/api/admin/roles"),
  addRole: (body: { principal: string; principal_type: string; role: string; domain?: string | null }) =>
    post("/api/admin/roles", body),
  removeRole: (id: number) => del(`/api/admin/roles/${id}`),
  settings: () => req<Record<string, unknown>>("/api/admin/settings"),
  putSetting: (key: string, value: unknown) => put(`/api/admin/settings/${key}`, { value }),
  catalogs: () => req<{ logical_name: string; physical_name: string; layer: string; env: string; description: string;
    managed: boolean }[]>("/api/admin/catalogs"),
  putCatalog: (logical: string, physical_name: string, managed: boolean) =>
    put(`/api/admin/catalogs/${logical}`, { physical_name, managed }),
  inventory: () => req<{ state: { last_run_at: string | null; status: string | null; error: string | null;
    counts: Record<string, number> | null }; job_id: string | null;
    last_run: { run_id: number; state: string | null; result: string | null; url: string } | null;
    inline_running: boolean }>("/api/admin/inventory"),
  runInventory: () => post<{ mode: string; run_id?: number }>("/api/admin/inventory/run"),
  log: () => req<{ id: number; actor: string; action: string; target: string | null; detail: unknown; at: string }[]>(
    "/api/admin/log"),
};
