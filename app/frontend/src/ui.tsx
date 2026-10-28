import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Impact, Level, PlanOp, Severity } from "./types";

// --------------------------------------------------------------------- icons
type IP = { className?: string };
const svg = (d: string) => (p: IP) => (
  <svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={d} />
  </svg>
);
export const Icon = {
  Shield: svg("M12 3l7 3v5c0 4.4-3 8.3-7 10-4-1.7-7-5.6-7-10V6l7-3z"),
  Grid: svg("M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"),
  Bell: svg("M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"),
  Users: svg("M17 20h5v-1a4 4 0 00-3-3.9M9 20H4v-1a4 4 0 013-3.9m6-1a4 4 0 10-4-4 4 4 0 004 4zm6 0a3 3 0 10-3-3"),
  Key: svg("M15 7a4 4 0 11-4 4l-6 6v3h3l1-1v-2h2v-2h2l1-1"),
  Plus: svg("M12 4v16m8-8H4"),
  Search: svg("M21 21l-4.3-4.3M10.5 18a7.5 7.5 0 110-15 7.5 7.5 0 010 15z"),
  Sun: svg("M12 3v2m0 14v2M5.6 5.6l1.4 1.4m10 10l1.4 1.4M3 12h2m14 0h2M5.6 18.4l1.4-1.4m10-10l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z"),
  Moon: svg("M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"),
  Refresh: svg("M4 4v5h5M20 20v-5h-5M20 9a8 8 0 00-14.9-3M4 15a8 8 0 0014.9 3"),
  Inbox: svg("M4 13h4l2 3h4l2-3h4M4 13V6a2 2 0 012-2h12a2 2 0 012 2v7M4 13v5a2 2 0 002 2h12a2 2 0 002-2v-5"),
  Route: svg("M6 19a2 2 0 100-4 2 2 0 000 4zM18 9a2 2 0 100-4 2 2 0 000 4zM6 15V9a4 4 0 014-4h4M18 9v6a4 4 0 01-4 4h-4"),
  Layers: svg("M12 3l9 5-9 5-9-5 9-5zm-9 9l9 5 9-5M3 16l9 5 9-5"),
  Settings: svg("M10.3 4.3a1.7 1.7 0 013.4 0 1.7 1.7 0 002.6 1.1 1.7 1.7 0 012.4 2.4 1.7 1.7 0 001.1 2.6 1.7 1.7 0 010 3.4 1.7 1.7 0 00-1.1 2.6 1.7 1.7 0 01-2.4 2.4 1.7 1.7 0 00-2.6 1.1 1.7 1.7 0 01-3.4 0 1.7 1.7 0 00-2.6-1.1 1.7 1.7 0 01-2.4-2.4 1.7 1.7 0 00-1.1-2.6 1.7 1.7 0 010-3.4 1.7 1.7 0 001.1-2.6 1.7 1.7 0 012.4-2.4 1.7 1.7 0 002.6-1.1zM12 15a3 3 0 100-6 3 3 0 000 6z"),
  User: svg("M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"),
  Database: svg("M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"),
  Check: svg("M5 13l4 4L19 7"),
  X: svg("M6 18L18 6M6 6l12 12"),
  Arrow: svg("M5 12h14m-6-6l6 6-6 6"),
  Back: svg("M19 12H5m6 6l-6-6 6-6"),
  Lock: svg("M7 11V8a5 5 0 0110 0v3M5 11h14v10H5z"),
};

// ---------------------------------------------------------------- routing
export type Route = { view: string; a?: string; b?: string };

export function parseHash(): Route {
  const parts = decodeURIComponent(window.location.hash.replace(/^#\/?/, "")).split("/").filter(Boolean);
  return { view: parts[0] || "overview", a: parts[1], b: parts.slice(2).join("/") || undefined };
}

export function go(view: string, a?: string, b?: string) {
  const path = [view, a, b].filter(Boolean).map((x) => encodeURIComponent(x as string)).join("/");
  window.location.hash = `/${path}`;
}

export function useRoute(): Route {
  const [r, setR] = useState<Route>(parseHash);
  useEffect(() => {
    const on = () => setR(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
}

// ------------------------------------------------------------------ data
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    fn().then(setData).catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { data, error, loading, reload: run, setData };
}

// ------------------------------------------------------------- elementos
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return <div className="flex items-center gap-2 text-text-dim py-6"><Spinner className="w-5 h-5" /> {label}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="card p-4 border-status-err/40 text-status-err text-sm flex items-center justify-between gap-3">
      <span>Erro: {error}</span>
      {onRetry && <button className="btn-ghost !py-1" onClick={onRetry}>Tentar de novo</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-text-dim text-sm py-6 text-center">{children}</div>;
}

export function Card({ title, subtitle, right, children, className = "" }: {
  title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={`card p-5 ${className}`}>
      {(title || right) && (
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            {title && <h3 className="font-semibold text-text">{title}</h3>}
            {subtitle && <p className="text-xs text-text-dim mt-0.5">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Stat({ label, value, hint, tone = "text", onClick }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: string; onClick?: () => void;
}) {
  return (
    <button onClick={onClick} disabled={!onClick}
      className={`card p-4 text-left ${onClick ? "hover:border-lava/50 cursor-pointer" : "cursor-default"}`}>
      <div className="text-text-dim text-[11px] uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-semibold mt-1 text-${tone}`}>{value}</div>
      {hint && <div className="text-xs text-text-dim mt-1">{hint}</div>}
    </button>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void;
}) {
  return (
    <div className="flex gap-1 border-b border-border mb-5 overflow-x-auto">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`px-3.5 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors ${
            value === t.id ? "border-lava text-text" : "border-transparent text-text-dim hover:text-text"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children, wide = false }: {
  title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-start justify-center p-6 overflow-y-auto" onClick={onClose}>
      <div className={`card w-full ${wide ? "max-w-5xl" : "max-w-2xl"} mt-10`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 className="font-semibold">{title}</h3>
          <button className="btn-ghost !p-1.5" onClick={onClose} aria-label="Fechar"><Icon.X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Table({ head, children, dense = false }: { head: ReactNode[]; children: ReactNode; dense?: boolean }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-navy-800 text-text-dim text-[11px] uppercase tracking-wide">
          <tr>{head.map((h, i) => <th key={i} className={`text-left ${dense ? "px-3 py-2" : "px-4 py-2.5"} font-medium`}>{h}</th>)}</tr>
        </thead>
        <tbody className="[&>tr]:border-t [&>tr]:border-border [&>tr:hover]:bg-surface-2/60">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`px-4 py-2.5 align-top ${className}`}>{children}</td>;
}

// ----------------------------------------------------------------- badges
const SEV: Record<Severity, string> = {
  info: "bg-status-info/15 text-status-info",
  warning: "bg-status-warn/15 text-status-warn",
  critical: "bg-status-err/15 text-status-err",
};
const SEV_LABEL: Record<Severity, string> = { info: "info", warning: "atenção", critical: "crítico" };
export function SeverityBadge({ s }: { s: Severity }) {
  return <span className={`badge ${SEV[s]}`}>{SEV_LABEL[s]}</span>;
}

const CLASS: Record<string, [string, string]> = {
  persona: ["persona", "bg-lava/15 text-lava"],
  idp_persona: ["IdP", "bg-status-info/15 text-status-info"],
  clearance: ["clearance", "bg-status-ok/15 text-status-ok"],
  legacy: ["legado", "bg-status-warn/15 text-status-warn"],
  clone: ["clone", "bg-status-err/15 text-status-err"],
  system: ["agentes/SPs", "bg-purple-500/15 text-purple-400"],
  other: ["outro", "bg-status-mute/15 text-status-mute"],
  user: ["usuário", "bg-status-mute/15 text-text-dim"],
  sp: ["service principal", "bg-purple-500/15 text-purple-400"],
  group: ["grupo", "bg-status-mute/15 text-text-dim"],
};
export function ClassBadge({ c }: { c: string | null | undefined }) {
  const [label, cls] = CLASS[c || "other"] || CLASS.other;
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function SensBadge({ s }: { s: string | null | undefined }) {
  if (!s) return null;
  const cls = s === "critical" ? "bg-status-err/15 text-status-err" : "bg-status-warn/15 text-status-warn";
  return <span className={`badge ${cls}`}><Icon.Lock className="w-3 h-3 mr-1" />{s === "critical" ? "crítico" : "restrito"}</span>;
}

const REQ: Record<string, [string, string]> = {
  pending: ["pendente", "bg-status-warn/15 text-status-warn"],
  applied: ["aplicado", "bg-status-ok/15 text-status-ok"],
  approved: ["aprovado", "bg-status-ok/15 text-status-ok"],
  rejected: ["rejeitado", "bg-status-err/15 text-status-err"],
  failed: ["falhou", "bg-status-err/15 text-status-err"],
  expired: ["expirado", "bg-status-mute/15 text-status-mute"],
  revoked: ["revogado", "bg-status-mute/15 text-status-mute"],
  cancelled: ["cancelado", "bg-status-mute/15 text-status-mute"],
  draft: ["rascunho", "bg-status-mute/15 text-status-mute"],
  executed: ["executada", "bg-status-ok/15 text-status-ok"],
  rolled_back: ["revertida", "bg-status-info/15 text-status-info"],
  open: ["aberto", "bg-status-err/15 text-status-err"],
  acknowledged: ["em análise", "bg-status-warn/15 text-status-warn"],
  resolved: ["resolvido", "bg-status-ok/15 text-status-ok"],
};
export function StatusBadge({ s }: { s: string }) {
  const [label, cls] = REQ[s] || [s, "bg-status-mute/15 text-status-mute"];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function Priv({ p }: { p: string }) {
  const strong = ["ALL_PRIVILEGES", "MODIFY", "MANAGE", "OWNER"].includes(p);
  const write = ["CREATE_TABLE", "CREATE_SCHEMA", "CREATE_VOLUME", "CREATE_FUNCTION"].includes(p);
  const cls = strong ? "bg-status-err/15 text-status-err" : write ? "bg-status-warn/15 text-status-warn"
    : p === "SELECT" ? "bg-status-info/15 text-status-info" : "bg-surface-2 text-text-dim";
  return <span className={`badge font-mono !text-[10px] ${cls}`}>{p.replace(/_/g, " ")}</span>;
}

export function Privs({ list }: { list: string[] }) {
  return <span className="inline-flex flex-wrap gap-1">{list.map((p) => <Priv key={p} p={p} />)}</span>;
}

export const LEVEL_STYLE: Record<Level, string> = {
  none: "bg-transparent text-text-dim/40",
  browse: "bg-status-mute/20 text-text-dim",
  read: "bg-status-info/25 text-status-info",
  write: "bg-status-warn/25 text-status-warn",
  all: "bg-status-err/25 text-status-err",
};
export const LEVEL_LABEL: Record<Level, string> = {
  none: "—", browse: "ver", read: "ler", write: "escrever", all: "total",
};

export const PERSONA_COLORS: Record<string, string> = {
  Consumer: "bg-status-mute/15 text-text-dim", Explorer: "bg-status-info/15 text-status-info",
  Creator: "bg-status-warn/15 text-status-warn", Conductor: "bg-status-ok/15 text-status-ok",
  Platform: "bg-lava/15 text-lava",
};

export function PathView({ path, start }: { path: string[]; start?: string }) {
  const items = [start, ...path].filter(Boolean) as string[];
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-xs text-text-dim">
      {items.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <Icon.Arrow className="w-3 h-3" />}<span className={i === items.length - 1 ? "text-text" : ""}>{p}</span>
        </span>
      ))}
    </span>
  );
}

export function fmtDate(s: string | null | undefined, withTime = false): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return withTime ? d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : d.toLocaleDateString("pt-BR");
}

export function short(name: string): string {
  return name.split(".").slice(-2).join(".");
}

export function describeOp(op: PlanOp): string {
  if (op.op === "grant" || op.op === "revoke") {
    return `${op.op === "grant" ? "GRANT" : "REVOKE"} ${(op.privileges || []).join(", ")} em ${op.securable} → ${op.principal}`;
  }
  return `${op.op === "add_member" ? "Adicionar" : "Remover"} ${op.member_name || op.member_id} ${op.op === "add_member" ? "em" : "de"} ${op.group}`;
}

export function PlanList({ plan }: { plan: PlanOp[] }) {
  if (!plan.length) return <Empty>Nenhuma operação: já está conforme o modelo.</Empty>;
  return (
    <ul className="space-y-1 text-sm font-mono">
      {plan.map((op, i) => (
        <li key={i} className="flex gap-2">
          <span className={op.op === "grant" || op.op === "add_member" ? "text-status-ok" : "text-status-err"}>
            {op.op === "grant" || op.op === "add_member" ? "+" : "−"}
          </span>
          <span className="text-text-dim break-all">{describeOp(op)}</span>
        </li>
      ))}
    </ul>
  );
}

export function ImpactView({ impact }: { impact: Impact | null | undefined }) {
  if (!impact) return <Empty>Sem prévia de impacto.</Empty>;
  const s = impact.summary;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <MiniStat label="Pessoas afetadas" value={s.affected} />
        <MiniStat label="Perdem acesso" value={s.losing} tone={s.losing ? "status-err" : "text"} />
        <MiniStat label="Ganham acesso" value={s.gaining} tone={s.gaining ? "status-ok" : "text"} />
        <MiniStat label={`Usavam o que perdem (${s.usage_days}d)`} value={s.used_lost_people}
          tone={s.used_lost_people ? "status-err" : "text"} />
      </div>
      {impact.people.length === 0 && <p className="text-xs text-text-dim">Nenhuma pessoa muda o que consegue ler (o acesso pode vir de outro grupo).</p>}
      {impact.people.length > 0 && (
        <div className="max-h-72 overflow-y-auto space-y-1.5">
          {impact.people.map((p) => (
            <div key={p.id} className="text-sm border border-border rounded-lg px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-text-dim">
                  {p.lost.length > 0 && <span className="text-status-err">−{p.lost.length} tabelas </span>}
                  {p.gained.length > 0 && <span className="text-status-ok">+{p.gained.length} tabelas</span>}
                </span>
              </div>
              {p.used_lost.length > 0 && (
                <div className="text-xs text-status-err mt-1">Usou recentemente: {p.used_lost.map(short).join(", ")}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function MiniStat({ label, value, tone = "text" }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-text-dim">{label}</div>
      <div className={`text-lg font-semibold text-${tone}`}>{value}</div>
    </div>
  );
}

export function Toast({ msg, kind = "ok", onClose }: { msg: string; kind?: "ok" | "err"; onClose: () => void }) {
  useEffect(() => { const t = setTimeout(onClose, 5000); return () => clearTimeout(t); }, [onClose]);
  return (
    <div className={`fixed bottom-6 right-6 z-50 card px-4 py-3 text-sm max-w-md ${kind === "err" ? "text-status-err border-status-err/40" : "text-status-ok border-status-ok/40"}`}>
      {msg}
    </div>
  );
}
