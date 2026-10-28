export interface Me {
  email: string | null;
  name: string;
  initials: string;
  authenticated: boolean;
}

export interface User {
  id: string;
  email: string;
  name: string;
  active: boolean;
  groups: string[];
  source: "workspace" | "account";   // workspace = SCIM da app; account = visto no audit
  n_workspaces: number | null;
}

export interface Workspace {
  workspace_id: string;
  workspace_name: string | null;
  workspace_url: string | null;
  n_open: number;
  is_app_workspace: boolean;
}

export interface Capability {
  code: string;
  label: string;
  description: string | null;
  audit_service: string;
  audit_actions: string[];
  default_severity: Severity;
  enabled: boolean;
  grant_count: number;
}

export interface Grant {
  id: number;
  principal: string;
  principal_type: "user" | "group";
  capability: string;
  workspace_id: string;   // '*' = account inteira
  allowed: boolean;
  granted_by: string | null;
  granted_at: string;
}

export interface EffectivePermission {
  capability: string;
  label: string;
  allowed: boolean;
  denied: boolean;
  source_principal: string | null;
  source_type: string | null;
  source_workspace?: string | null;
}

export type Severity = "info" | "warning" | "critical";
export type AlertStatus = "open" | "investigating" | "resolved" | "false_positive";

export interface Alert {
  id: number;
  principal: string;
  capability: string;
  asset_type: string | null;
  asset_id: string | null;
  asset_name: string | null;
  service_name: string | null;
  action_name: string | null;
  workspace_id: string | null;
  workspace_name: string | null;
  workspace_url: string | null;
  source_ip: string | null;
  event_time: string | null;
  severity: Severity;
  status: AlertStatus;
  detected_at: string;
  resolved_by: string | null;
  resolved_at: string | null;
  notes: string | null;
}

export interface AlertStats {
  by_status: { status: string; n: number }[];
  by_severity: { severity: string; n: number }[];
  by_capability: { capability: string; n: number }[];
  top_offenders: { principal: string; n: number }[];
  by_workspace: { workspace_id: string; workspace_name: string | null; n: number }[];
}

export interface AlertPage {
  items: Alert[];
  total: number;
  limit: number;
  offset: number;
}

export interface NLResult {
  status:
    | "created" | "denied" | "unsupported" | "need_info"
    | "unclear" | "no_obo" | "no_capability" | "error";
  capability?: string;
  label?: string;
  name?: string;
  asset_id?: string | null;
  missing?: string[];
  message?: string;
  plan?: { capability?: string; name?: string; spec?: Record<string, unknown>; message?: string };
}

export interface AgentStep {
  tool: string;
  args: Record<string, unknown>;
  result: string;
}
export interface AgentResult {
  answer: string | null;
  transcript: AgentStep[];
}

export interface Conversation {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
  n_messages: number;
}
export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string | null;
  transcript: AgentStep[] | null;
  created_at: string;
}
export interface ChatResponse {
  conversation_id: number;
  message_id: number | null;
  answer: string;
  transcript: AgentStep[];
}

export interface GenieAnswer {
  conversation_id: string;
  message_id: string;
  answer: string | null;
  sql: string | null;
  rows: Record<string, unknown>[] | null;
}
