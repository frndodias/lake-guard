import type { AlertStatus, Severity } from "./types";

// --------------------------------------------------------------------- icons
type IP = { className?: string };
export const Icon = {
  Shield: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3l7 3v5c0 4.4-3 8.3-7 10-4-1.7-7-5.6-7-10V6l7-3z" /></svg>),
  Grid: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" /></svg>),
  Bell: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg>),
  Users: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-1a4 4 0 00-3-3.9M9 20H4v-1a4 4 0 013-3.9m6-1a4 4 0 10-4-4 4 4 0 004 4zm6 0a3 3 0 10-3-3" /></svg>),
  Key: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a4 4 0 11-4 4l-6 6v3h3l1-1v-2h2v-2h2l1-1" /></svg>),
  Plus: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>),
  Chat: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h8M8 14h5m-9 6l3-3h9a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v13z" /></svg>),
  Trash: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-7 0l1 12a1 1 0 001 1h4a1 1 0 001-1l1-12" /></svg>),
  Sun: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v2m0 14v2M5.6 5.6l1.4 1.4m10 10l1.4 1.4M3 12h2m14 0h2M5.6 18.4l1.4-1.4m10-10l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z" /></svg>),
  Moon: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" /></svg>),
  Refresh: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h5M20 20v-5h-5M20 9a8 8 0 00-14.9-3M4 15a8 8 0 0014.9 3" /></svg>),
  Play: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 4.5v15l13-7.5-13-7.5z" /></svg>),
  Pencil: (p: IP) => (<svg {...p} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.5 5.5l3 3M4 20l1-4L16 5a2.1 2.1 0 013 3L8 19l-4 1z" /></svg>),
};

/** Nome do workspace quando conhecido; senão o id. */
export function wsLabel(id: string | null | undefined, name?: string | null): string {
  if (!id) return "—";
  if (id === "*") return "Todos os workspaces";
  // o audit registra operações de metastore do UC (external location, share…) com id 0
  if (id === "0") return "Unity Catalog (nível da account)";
  return name || `Workspace ${id}`;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

const SEV: Record<Severity, string> = {
  info: "bg-status-info/15 text-status-info",
  warning: "bg-status-warn/15 text-status-warn",
  critical: "bg-status-err/15 text-status-err",
};
export function SeverityBadge({ s }: { s: Severity }) {
  return <span className={`badge ${SEV[s]}`}>{s}</span>;
}

const ST: Record<AlertStatus, string> = {
  open: "bg-status-err/15 text-status-err",
  investigating: "bg-status-warn/15 text-status-warn",
  resolved: "bg-status-ok/15 text-status-ok",
  false_positive: "bg-status-mute/15 text-status-mute",
};
const ST_LABEL: Record<AlertStatus, string> = {
  open: "aberto",
  investigating: "em análise",
  resolved: "resolvido",
  false_positive: "falso-positivo",
};
export function StatusBadge({ s }: { s: AlertStatus }) {
  return <span className={`badge ${ST[s]}`}>{ST_LABEL[s]}</span>;
}
