import { useEffect, useState } from "react";
import { api } from "./api";
import type { Me, Workspace } from "./types";
import { useTheme } from "./useTheme";
import { Icon, wsLabel } from "./ui";
import { Sidebar, type ViewId } from "./components/Sidebar";
import { DashboardView } from "./components/DashboardView";
import { AlertsView } from "./components/AlertsView";
import { UsersView } from "./components/UsersView";
import { RolesView } from "./components/RolesView";
import { CreateAssetView } from "./components/CreateAssetView";
import { AgentView } from "./components/AgentView";

const TITLES: Record<ViewId, { title: string; subtitle: string }> = {
  dashboard: { title: "Visão geral", subtitle: "Panorama das violações e da postura de governança na account" },
  alerts: { title: "Alertas", subtitle: "Assets criados sem permissão — investigue e remedie" },
  users: { title: "Usuários", subtitle: "Usuários da account e suas permissões efetivas" },
  roles: { title: "Permissões", subtitle: "Cadastro do que cada usuário/grupo pode criar" },
  create: { title: "Criar asset", subtitle: "Criação governada — só o que você tem permissão" },
  agent: { title: "Genie", subtitle: "Pergunte em linguagem natural sobre permissões e eventos" },
};

// Telas em que o filtro global de workspace se aplica
const WS_FILTER_VIEWS: ViewId[] = ["dashboard", "alerts", "users"];

export default function App() {
  const [view, setView] = useState<ViewId>("dashboard");
  const [me, setMe] = useState<Me | null>(null);
  const [openAlerts, setOpenAlerts] = useState(0);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [appWorkspaceId, setAppWorkspaceId] = useState<string>("");
  const [workspaceId, setWorkspaceId] = useState<string>(""); // "" = todos
  const { theme, toggle } = useTheme();

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  const refreshWorkspaces = () => {
    api.workspaces()
      .then((r) => { setWorkspaces(r.workspaces); setAppWorkspaceId(r.app_workspace_id); })
      .catch(() => {});
  };

  const refreshOpenAlerts = () => {
    api.alertStats(workspaceId || undefined)
      .then((s) => setOpenAlerts(Number(s.by_status.find((x) => x.status === "open")?.n ?? 0)))
      .catch(() => {});
  };
  useEffect(refreshOpenAlerts, [view, workspaceId]);
  useEffect(refreshWorkspaces, [view]);

  const onAlertsChange = () => { refreshOpenAlerts(); refreshWorkspaces(); };
  const head = TITLES[view];

  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar view={view} onNav={setView} me={me} openAlerts={openAlerts} />
      <main className="flex-1 min-w-0">
        <header className="h-16 border-b border-border flex items-center justify-between px-8 sticky top-0 bg-bg/90 backdrop-blur z-10">
          <div>
            <h1 className="text-lg font-semibold text-text">{head.title}</h1>
            <p className="text-xs text-text-dim">{head.subtitle}</p>
          </div>
          <div className="flex items-center gap-2">
            {WS_FILTER_VIEWS.includes(view) && (
              <select
                className="input !py-1.5 max-w-[320px]"
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
                title="Filtrar por workspace"
              >
                <option value="">Todos os workspaces</option>
                {workspaces.map((w) => (
                  <option key={w.workspace_id} value={w.workspace_id}>
                    {wsLabel(w.workspace_id, w.workspace_name)}
                    {w.is_app_workspace ? " (app)" : ""}
                    {w.n_open ? ` · ${w.n_open} abertos` : ""}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={toggle}
              className="btn-ghost !p-2"
              title={theme === "dark" ? "Mudar para tema claro" : "Mudar para tema escuro"}
              aria-label="Alternar tema"
            >
              {theme === "dark" ? <Icon.Sun className="w-5 h-5" /> : <Icon.Moon className="w-5 h-5" />}
            </button>
          </div>
        </header>
        <div className="p-8 max-w-[1400px]">
          {view === "dashboard" && (
            <DashboardView
              workspaceId={workspaceId}
              onGoAlerts={() => setView("alerts")}
              onPickWorkspace={(id) => { setWorkspaceId(id); setView("alerts"); }}
            />
          )}
          {view === "alerts" && (
            <AlertsView workspaceId={workspaceId} appWorkspaceId={appWorkspaceId} onChange={onAlertsChange} />
          )}
          {view === "users" && <UsersView workspaceId={workspaceId} />}
          {view === "roles" && <RolesView workspaces={workspaces} />}
          {view === "create" && <CreateAssetView />}
          {view === "agent" && <AgentView />}
        </div>
      </main>
    </div>
  );
}
