export type Role = { role: "admin" | "steward" | "dpo" | "auditor"; domain: string | null; via: string };

export type Me = {
  email: string; name: string; initials: string; roles: Role[];
  is_admin: boolean; is_dpo: boolean; is_auditor: boolean; steward_domains: string[]; can_view: boolean;
  flags: Record<string, unknown>; badges: { pending: number; critical_alerts: number };
};

export type Severity = "info" | "warning" | "critical";
export type Level = "none" | "browse" | "read" | "write" | "all";

export type Brief = { id: string; type: string; name: string; label: string; class: string | null; persona_code?: string | null };

export type Alert = {
  id: number; rule: string; severity: Severity; title: string; principal: string | null; object: string | null;
  detail: Record<string, unknown>; fixable: boolean; status: string; first_seen: string; last_seen: string;
  resolved_by?: string | null;
};

export type Overview = {
  inventory: { last_run_at: string | null; status: string | null; error: string | null; counts: Record<string, number> | null } | null;
  identities: { users: number; sps: number; groups: number; groups_by_class: Record<string, number> };
  personas: { exactly_one: number; none: number; multiple: number; migrated_pct: number };
  grants: { total: number; outside_model: number; direct_user: number; outside_pct: number };
  alerts: { open: number; by_severity: Record<string, number>; top: Alert[] };
  requests_pending: number;
  catalogs: { logical: string; physical: string; env: string }[];
  matrix: {
    id: string; name: string; type: string; class: string | null; humans: number | null;
    cells: Record<string, { level: Level; privileges: string[]; schema_grants: number }>;
  }[];
};

export type IdentityRow = Brief & {
  active?: boolean; in_scope?: boolean; groups: number; alerts: number;
  personas?: string[]; readable?: number; last_activity?: string | null; reads_90d?: number;
  members?: number; humans?: number; grants?: number;
};

export type GrantSource = {
  securable: string; sec_type: string; privileges: string[]; via: Brief; direct: boolean; path: string[];
  tables: number; sensitivity: string | null;
};

export type IdentityDetail = {
  principal: Brief & { active?: boolean; in_scope?: boolean; display_name?: string | null };
  groups: (Brief & { depth: number; path: string[] })[];
  alerts: { id: number; rule: string; severity: Severity; title: string; object: string | null }[];
  personas?: string[];
  grants?: GrantSource[];
  readable?: { table: string; sensitivity: string | null; reads_90d: number; last_used: string | null; via: string | null }[];
  usage?: { securable: string; action: string; n: number; last_day: string; source: string; has_access: boolean; sensitivity: string | null }[];
  creations?: { capability: string; asset_name: string | null; location: string | null; workspace_id: string | null; event_time: string; source: string }[];
  can_vs_use?: { readable: number; used: number; unused: number; sensitive_readable: number };
  manual_memberships?: { group_name: string; justification: string; approved_by: string; expires_at: string | null; created_at: string }[];
  members?: (Brief & { depth: number; path: string[] })[];
  direct_grants?: GrantSource[];
  mapping?: { action: string; target: string | null; rationale: string | null; status: string } | null;
  grants_vs_use?: { table: string; reads_90d: number; sensitivity: string | null }[];
  persona?: string;
};

export type AssetNode = {
  name: string; label: string; type: string; owner: string | null; domain: string | null; sensitivity: string | null;
  catalog_logical: string | null; grants: number; tables: number; reads_90d: number; readers_90d: number;
  children: AssetNode[];
};

export type AssetDetail = {
  securable: { full_name: string; type: string; owner: string | null; created_by: string | null; created_at: string | null;
    domain: string | null; catalog_logical: string | null; sensitivity: string | null };
  direct_grants: { principal: Partial<Brief> & { label: string }; privileges: string[]; humans: number | null }[];
  inherited_grants: { securable: string; principal: Partial<Brief> & { label: string }; privilege: string }[];
  top_users: (Brief & { n: number; last_day: string | null })[];
  readers?: (Brief & { via: string | null; granted_on: string | null; path: string[]; has_clearance: boolean; reads_90d: number })[];
  clearance_group?: string | null;
  unused: boolean;
};

export type GraphNode = { id: string; kind: string; label: string; class?: string | null; ring: number; full_name?: string;
  sec_type?: string; sensitivity?: string | null };
export type GraphData = { nodes: GraphNode[]; edges: { from: string; to: string; kind: string; privileges?: string[] }[] };

export type PersonaGrant = { catalog: string; schema_scope: string | null; privileges: string[] };

export type PersonaRow = {
  code: string; label: string; category: string; description: string; group_name: string; idp_group_name: string;
  version: number; group: string; group_exists: boolean; gap: Record<string, number>; people: number; via_idp: number;
  manual: number; conflicts: number; capabilities: string[]; grants: PersonaGrant[];
};

export type PlanOp = {
  op: "grant" | "revoke" | "add_member" | "remove_member"; sec_type?: string; securable?: string; principal?: string;
  privileges?: string[]; group?: string; group_id?: string; member_id?: string; member_name?: string; member_type?: string;
};

export type Impact = {
  people: { id: string; name: string; type: string; lost: string[]; gained: string[]; used_lost: string[] }[];
  summary: { affected: number; losing: number; gaining: number; lost_tables: number; gained_tables: number;
    used_lost_people: number; usage_days: number };
};

export type PersonaMember = {
  id: string; label: string; type: string; source: string; people?: { id: string; label: string }[];
  justification?: string | null; expires_at?: string | null; approved_by?: string | null;
};

export type PersonaDetail = {
  persona: PersonaRow;
  grants: PersonaGrant[];
  expanded: { sec_type: string; securable: string; privileges: string[]; managed: boolean; catalog_logical: string }[];
  gap: { persona: string; group: string; group_id: string | null; group_exists: boolean;
    items: { securable: string; sec_type: string; privilege: string; status: string }[]; counts: Record<string, number> };
  plan: PlanOp[];
  members: { group: string; group_id: string | null; direct: PersonaMember[]; people: number; via_idp: number; manual: number;
    conflicts: { id: string; label: string; personas: string[] }[] };
  capabilities: string[];
  versions: { version: number; changed_by: string; changed_at: string; change_id: number | null }[];
  pending: { id: number; kind: string; title: string; status: string; requested_by: string; created_at: string }[];
};

export type PersonaMeta = {
  privileges: string[];
  capabilities: { code: string; label: string; severity: string }[];
  catalogs: { logical: string; physical: string; managed: boolean; env: string; description: string }[];
  schema_scopes: string[];
};

export type Preview = { plan: PlanOp[]; impact: Impact; script: string; desired_added: [string, string][];
  desired_removed: [string, string][] };

export type ChangeRequest = {
  id: number; kind: string; title: string; target: string | null; domain: string | null; payload: Record<string, unknown>;
  plan: PlanOp[]; impact: Impact | null; justification: string | null; duration_days: number | null;
  requires_dpo: boolean; status: string; requested_by: string; approved_by: string | null; approved_at: string | null;
  dpo_approved_by: string | null; rejected_by: string | null; decision_note: string | null; applied_at: string | null;
  expires_at: string | null; result: { ok?: boolean; results?: { op: string; ok: boolean; error?: string }[] } | null;
  created_at: string; can_approve?: string[]; is_mine?: boolean;
};

export type Domain = {
  code: string; name: string; schema_name: string; owner: string | null; sensitivity: string; clearance_group: string | null;
  description: string | null; schema_full_name: string; schema_exists: boolean; tables: number; sensitive_tables: number;
  clearance_physical: string | null; clearance_exists: boolean; clearance_members: string[]; clearance_plan: PlanOp[];
  stewards: string[];
};
export type DomainList = { domains: Domain[]; unregistered_schemas: string[] };

export type RequestTargets = {
  clearance: { code: string; name: string; sensitivity: string; group: string; requires_dpo: boolean; exists: boolean }[];
  personas: { code: string; label: string; group: string }[];
  people: { id: string; label: string; type: string }[];
  me: string | null;
};

export type MigrationGroup = {
  group: string; group_id: string; class: string; members: number; humans: number; grants: number;
  action: string; target: string | null; rationale: string; score: number | null;
  suggested_action: string; suggested_target: string | null;
  mapping: { status?: string; suggested?: boolean; updated_by?: string } | null;
};
export type MigrationGroups = { groups: MigrationGroup[]; actions: string[]; personas: string[]; domains: string[] };

export type Wave = { id: number; name: string; wave_order: number; groups: string[]; status: string; change_id: number | null;
  request_status: string | null; created_by: string; created_at: string; executed_at: string | null };
export type WavePreview = { wave: Wave; plan: PlanOp[]; inverse: PlanOp[]; notes: string[]; impact: Impact; script: string };

export type AlertList = { alerts: Alert[]; counts: { rule: string; severity: Severity; n: number }[]; rules: Record<string, string> };
