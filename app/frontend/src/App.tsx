import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Me } from "./types";
import { useTheme } from "./useTheme";
import { Icon, Loading, Toast, go, useRoute } from "./ui";
import { OverviewView } from "./views/Overview";
import { ExploreView } from "./views/Explore";
import { PersonasView } from "./views/Personas";
import { DomainsView } from "./views/Domains";
import { RequestsView } from "./views/Requests";
import { MigrationView } from "./views/Migration";
import { AlertsView } from "./views/Alerts";
import { AdminView } from "./views/Admin";
import { MyAccessView } from "./views/MyAccess";

type Ctx = { me: Me; notify: (msg: string, kind?: "ok" | "err") => void; refreshMe: () => void };
const AppCtx = createContext<Ctx | null>(null);
export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("AppCtx ausente");
  return c;
}

type NavItem = { id: string; label: string; icon: (p: { className?: string }) => JSX.Element; badge?: number;
  needsView?: boolean; title: string; subtitle: string };

export default function App() {
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const [me, setMe] = useState<Me | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);

  const refreshMe = useCallback(() => {
    api.me().then(setMe).catch((e: Error) => setErr(e.message));
  }, []);
  useEffect(refreshMe, [refreshMe, route.view]);
  const notify = useCallback((msg: string, kind: "ok" | "err" = "ok") => setToast({ msg, kind }), []);

  if (err && !me) return <div className="p-10 text-status-err">Não foi possível carregar o usuário: {err}</div>;
  if (!me) return <div className="p-10"><Loading /></div>;

  const nav: NavItem[] = [
    { id: "overview", label: "Diagnóstico", icon: Icon.Grid, needsView: true, title: "Diagnóstico",
      subtitle: "Como os acessos estão hoje e o quanto se distanciam do modelo de personas" },
    { id: "explore", label: "Visão 360", icon: Icon.Search, needsView: true, title: "Visão 360",
      subtitle: "Quem pode × quem usa — por identidade, grupo ou dado" },
    { id: "personas", label: "Personas", icon: Icon.Layers, needsView: true, title: "Personas",
      subtitle: "Modelo desejado: permissões, membros, prévia de impacto e aplicação" },
    { id: "domains", label: "Domínios e clearance", icon: Icon.Database, needsView: true, title: "Domínios e clearance",
      subtitle: "Schemas de domínio, sensibilidade, clearance e stewards" },
    { id: "requests", label: "Solicitações", icon: Icon.Inbox, badge: me.badges.pending, title: "Solicitações",
      subtitle: "Pedir acesso com prazo · aprovar (steward e DPO) · revogar" },
    { id: "migration", label: "Migração", icon: Icon.Route, needsView: true, title: "Migração",
      subtitle: "De-para dos grupos legados e ondas com prévia de impacto e rollback" },
    { id: "alerts", label: "Regras e alertas", icon: Icon.Bell, badge: me.badges.critical_alerts, needsView: true,
      title: "Regras e alertas", subtitle: "Desvios do modelo detectados continuamente" },
    { id: "me", label: "Meu acesso", icon: Icon.User, title: "Meu acesso", subtitle: "O que você pode acessar e por quê" },
    { id: "admin", label: "Administração", icon: Icon.Settings, needsView: true, title: "Administração",
      subtitle: "Papéis do app, catalogs, configurações, inventário e trilha de auditoria" },
  ];
  const visible = nav.filter((n) => !n.needsView || me.can_view);
  const current = visible.find((n) => n.id === route.view) || visible[0];
  const demo = Boolean(me.flags.demo_mode);

  let body: ReactNode;
  switch (current.id) {
    case "overview": body = <OverviewView />; break;
    case "explore": body = <ExploreView route={route} />; break;
    case "personas": body = <PersonasView route={route} />; break;
    case "domains": body = <DomainsView />; break;
    case "requests": body = <RequestsView route={route} />; break;
    case "migration": body = <MigrationView />; break;
    case "alerts": body = <AlertsView />; break;
    case "admin": body = <AdminView />; break;
    default: body = <MyAccessView />;
  }

  return (
    <AppCtx.Provider value={{ me, notify, refreshMe }}>
      <div className="flex min-h-screen bg-bg">
        <aside className="w-64 shrink-0 bg-navy-900 border-r border-border flex flex-col h-screen sticky top-0">
          <div className="flex items-center gap-2.5 px-5 h-16 border-b border-border">
            <Icon.Shield className="w-7 h-7 text-lava" />
            <div>
              <div className="font-semibold text-text leading-tight">Lakeguard</div>
              <div className="text-[11px] text-text-dim">Governança de acessos</div>
            </div>
          </div>
          <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
            {visible.map(({ id, label, icon: I, badge }) => {
              const active = current.id === id;
              return (
                <button key={id} onClick={() => go(id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    active ? "bg-lava text-white" : "text-text-dim hover:bg-surface-2 hover:text-text"}`}>
                  <I className="w-5 h-5" />
                  <span className="flex-1 text-left">{label}</span>
                  {!!badge && (
                    <span className={`badge ${active ? "bg-white/20 text-white" : "bg-status-err/20 text-status-err"}`}>{badge}</span>
                  )}
                </button>
              );
            })}
          </nav>
          <div className="border-t border-border p-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-lava/20 text-lava grid place-items-center text-sm font-semibold">{me.initials}</div>
              <div className="min-w-0">
                <div className="text-sm text-text truncate">{me.name}</div>
                <div className="text-[11px] text-text-dim truncate">{me.email}</div>
              </div>
            </div>
            <div className="flex flex-wrap gap-1 mt-2">
              {me.is_admin && <span className="badge bg-lava/15 text-lava">admin</span>}
              {me.is_dpo && <span className="badge bg-status-ok/15 text-status-ok">DPO</span>}
              {me.is_auditor && <span className="badge bg-status-info/15 text-status-info">auditor</span>}
              {me.steward_domains.length > 0 && (
                <span className="badge bg-status-warn/15 text-status-warn" title={me.steward_domains.join(", ")}>
                  steward · {me.steward_domains.length}
                </span>
              )}
            </div>
          </div>
        </aside>
        <main className="flex-1 min-w-0">
          <header className="h-16 border-b border-border flex items-center justify-between px-8 sticky top-0 bg-bg/90 backdrop-blur z-10">
            <div>
              <h1 className="text-lg font-semibold text-text">{current.title}</h1>
              <p className="text-xs text-text-dim">{current.subtitle}</p>
            </div>
            <div className="flex items-center gap-2">
              {demo && <span className="badge bg-status-warn/15 text-status-warn" title="Ambiente de demonstração: identidades dbdemo-*, catalogs lg_* e uso simulado">modo demo</span>}
              <button onClick={toggle} className="btn-ghost !p-2" aria-label="Alternar tema"
                title={theme === "dark" ? "Tema claro" : "Tema escuro"}>
                {theme === "dark" ? <Icon.Sun className="w-5 h-5" /> : <Icon.Moon className="w-5 h-5" />}
              </button>
            </div>
          </header>
          <div className="p-8 max-w-[1500px]">{body}</div>
        </main>
      </div>
      {toast && <Toast msg={toast.msg} kind={toast.kind} onClose={() => setToast(null)} />}
    </AppCtx.Provider>
  );
}
