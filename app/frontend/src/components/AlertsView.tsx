import { useEffect, useState } from "react";
import { api } from "../api";
import type { Alert, AlertStatus } from "../types";
import { SeverityBadge, Spinner, StatusBadge, Icon, wsLabel } from "../ui";

const STATUS_OPTS: { v: string; label: string }[] = [
  { v: "", label: "Todos" },
  { v: "open", label: "Abertos" },
  { v: "investigating", label: "Em análise" },
  { v: "resolved", label: "Resolvidos" },
  { v: "false_positive", label: "Falso-positivo" },
];

type DetStatus = Awaited<ReturnType<typeof api.detectionStatus>>;

const PAGE = 100;

export function AlertsView({
  workspaceId, appWorkspaceId, onChange,
}: {
  workspaceId: string;
  appWorkspaceId: string;
  onChange: () => void;
}) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [status, setStatus] = useState("open");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [det, setDet] = useState<DetStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const filters = { status, workspace_id: workspaceId };

  const load = () => {
    setLoading(true);
    api.alerts({ ...filters, limit: PAGE, offset: 0 })
      .then((r) => { setAlerts(r.items); setTotal(r.total); })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [status, workspaceId]);

  const loadMore = () => {
    setLoadingMore(true);
    api.alerts({ ...filters, limit: PAGE, offset: alerts.length })
      .then((r) => { setAlerts((a) => [...a, ...r.items]); setTotal(r.total); })
      .catch((e) => setErr(e.message))
      .finally(() => setLoadingMore(false));
  };

  const loadDet = () => { api.detectionStatus().then(setDet).catch(() => {}); };
  useEffect(loadDet, []);

  const runNow = async () => {
    setRunning(true); setToast(null); setErr(null);
    try {
      await api.runDetection();
      setToast("Detecção disparada — roda em ~1-2 min. Clique em Atualizar para ver os novos alertas.");
      setTimeout(loadDet, 4000);
    } catch (e) { setErr((e as Error).message); } finally { setRunning(false); }
  };

  const setAlertStatus = async (a: Alert, s: AlertStatus) => {
    setBusy(a.id);
    try {
      await api.patchAlert(a.id, { status: s });
      load(); onChange();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };

  const remediate = async (a: Alert) => {
    if (!confirm(`Deletar o asset "${a.asset_name ?? a.asset_id}" (${a.capability}) e resolver o alerta?`)) return;
    setBusy(a.id);
    try {
      const r = await api.remediate(a.id);
      alert(r.ok ? "Asset removido e alerta resolvido." : `Falha: ${r.detail}`);
      load(); onChange();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          {STATUS_OPTS.map((o) => (
            <button
              key={o.v}
              onClick={() => setStatus(o.v)}
              className={`btn ${status === o.v ? "btn-primary" : "btn-ghost"}`}
            >{o.label}</button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost" onClick={() => { load(); loadDet(); }} disabled={loading}>
            <Icon.Refresh className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> Atualizar
          </button>
          <button className="btn-primary" onClick={runNow}
            disabled={running || (det !== null && !det.job_configured)}
            title="Dispara o job que analisa o audit log agora">
            {running ? <Spinner className="w-4 h-4" /> : <Icon.Play className="w-4 h-4" />} Rodar detecção
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-text-dim">
        <span>{total.toLocaleString("pt-BR")} alertas neste filtro{alerts.length < total ? ` · mostrando ${alerts.length}` : ""}</span>
        <span>
          {det?.state?.last_run_at
            ? <>Última análise: {new Date(det.state.last_run_at).toLocaleString("pt-BR")}
                {det.state.last_run_status && <> · <span className={det.state.last_run_status === "ok" ? "text-status-ok" : "text-status-err"}>{det.state.last_run_status}</span></>}</>
            : "Detecção ainda não executada"}
        </span>
      </div>

      {toast && <div className="card p-3 text-sm" style={{ color: "rgb(var(--text))" }}>{toast}</div>}
      {err && <div className="card p-4 text-status-err">Erro: {err}</div>}
      {loading ? (
        <div className="flex items-center gap-2 text-text-dim"><Spinner className="w-5 h-5" /> Carregando…</div>
      ) : alerts.length === 0 ? (
        <div className="card p-8 text-center text-text-dim">Nenhum alerta neste filtro.</div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-navy-800 text-text-dim text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3">Usuário</th>
                <th className="text-left px-4 py-3">Workspace</th>
                <th className="text-left px-4 py-3">Asset</th>
                <th className="text-left px-4 py-3">Severidade</th>
                <th className="text-left px-4 py-3">Quando</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-right px-4 py-3">Ações</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className="border-t border-border hover:bg-surface-2/50">
                  <td className="px-4 py-3">
                    <div className="text-text">{a.principal}</div>
                    <div className="text-text-dim text-xs">{a.source_ip}</div>
                  </td>
                  <td className="px-4 py-3 max-w-[200px]">
                    <div className="text-text truncate" title={a.workspace_id ?? ""}>{wsLabel(a.workspace_id, a.workspace_name)}</div>
                    {a.workspace_id === appWorkspaceId && <div className="text-text-dim text-xs">workspace da app</div>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-text">{a.asset_name ?? a.asset_id ?? "—"}</div>
                    <div className="text-text-dim text-xs">{a.capability} · {a.action_name}</div>
                  </td>
                  <td className="px-4 py-3"><SeverityBadge s={a.severity} /></td>
                  <td className="px-4 py-3 text-text-dim">
                    {a.event_time ? new Date(a.event_time).toLocaleString("pt-BR") : "—"}
                  </td>
                  <td className="px-4 py-3"><StatusBadge s={a.status} /></td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      {a.status !== "resolved" && a.status !== "false_positive" && (
                        <>
                          <button className="btn-ghost !px-2 !py-1 text-xs" disabled={busy === a.id}
                            onClick={() => setAlertStatus(a, "false_positive")}>Falso+</button>
                          <button className="btn-ghost !px-2 !py-1 text-xs" disabled={busy === a.id}
                            onClick={() => setAlertStatus(a, "resolved")}>Resolver</button>
                          {a.workspace_id === appWorkspaceId ? (
                            <button className="btn-primary !px-2 !py-1 text-xs" disabled={busy === a.id}
                              onClick={() => remediate(a)} title="Deletar asset e resolver">
                              <Icon.Trash className="w-3.5 h-3.5" /> Remediar
                            </button>
                          ) : a.workspace_url ? (
                            <a className="btn-ghost !px-2 !py-1 text-xs" target="_blank" rel="noreferrer"
                              href={a.workspace_url.startsWith("http") ? a.workspace_url : `https://${a.workspace_url}`}
                              title="A app não tem acesso a este workspace — resolva lá">
                              Abrir workspace
                            </a>
                          ) : (
                            <span className="text-text-dim text-xs" title="A app só remedia no próprio workspace">remediar no workspace</span>
                          )}
                        </>
                      )}
                      {busy === a.id && <Spinner className="w-4 h-4 text-text-dim" />}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {alerts.length < total && (
            <div className="border-t border-border p-3 text-center">
              <button className="btn-ghost" onClick={loadMore} disabled={loadingMore}>
                {loadingMore && <Spinner className="w-4 h-4" />} Carregar mais
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
