import { Icon } from "../ui";
import type { Me } from "../types";

export type ViewId = "dashboard" | "alerts" | "users" | "roles" | "create" | "agent";

const NAV: { id: ViewId; label: string; icon: (p: { className?: string }) => JSX.Element }[] = [
  { id: "dashboard", label: "Visão geral", icon: Icon.Grid },
  { id: "alerts", label: "Alertas", icon: Icon.Bell },
  { id: "users", label: "Usuários", icon: Icon.Users },
  { id: "roles", label: "Permissões", icon: Icon.Key },
  { id: "create", label: "Criar asset", icon: Icon.Plus },
  { id: "agent", label: "Genie", icon: Icon.Chat },
];

export function Sidebar({
  view, onNav, me, openAlerts,
}: {
  view: ViewId;
  onNav: (v: ViewId) => void;
  me: Me | null;
  openAlerts: number;
}) {
  return (
    <aside className="w-64 shrink-0 bg-navy-900 border-r border-border flex flex-col h-screen sticky top-0">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-border">
        <Icon.Shield className="w-7 h-7 text-lava" />
        <div>
          <div className="font-semibold text-text leading-tight">Lakeguard</div>
          <div className="text-[11px] text-text-dim">Governança de assets</div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(({ id, label, icon: I }) => {
          const active = view === id;
          return (
            <button
              key={id}
              onClick={() => onNav(id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                active ? "bg-lava text-white" : "text-text-dim hover:bg-surface-2 hover:text-text"
              }`}
            >
              <I className="w-5 h-5" />
              <span className="flex-1 text-left">{label}</span>
              {id === "alerts" && openAlerts > 0 && (
                <span className={`badge ${active ? "bg-white/20 text-white" : "bg-status-err/20 text-status-err"}`}>
                  {openAlerts}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-border p-4 flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-lava/20 text-lava grid place-items-center text-sm font-semibold">
          {me?.initials ?? "?"}
        </div>
        <div className="min-w-0">
          <div className="text-sm text-text truncate">{me?.name ?? "…"}</div>
          <div className="text-[11px] text-text-dim truncate">{me?.email ?? "não autenticado"}</div>
        </div>
      </div>
    </aside>
  );
}
