import { useEffect, useState } from "react";
import { api } from "../api";
import type { AlertStats } from "../types";
import { Spinner, wsLabel } from "../ui";

function Stat({ label, value, tone = "text" }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="card p-5">
      <div className="text-text-dim text-xs uppercase tracking-wide">{label}</div>
      <div className={`text-3xl font-semibold mt-1 text-${tone}`}>{value}</div>
    </div>
  );
}

export function DashboardView({
  workspaceId, onGoAlerts, onPickWorkspace,
}: {
  workspaceId: string;
  onGoAlerts: () => void;
  onPickWorkspace: (id: string) => void;
}) {
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.alertStats(workspaceId || undefined)
      .then(setStats)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  if (loading) return <div className="flex items-center gap-2 text-text-dim"><Spinner className="w-5 h-5" /> Carregando…</div>;
  if (err) return <div className="card p-6 text-status-err">Erro: {err}</div>;
  if (!stats) return null;

  const num = (arr: { n: number }[]) => arr.reduce((s, r) => s + Number(r.n), 0);
  const open = stats.by_status.find((s) => s.status === "open")?.n ?? 0;
  const critical = stats.by_severity.find((s) => s.severity === "critical")?.n ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Alertas abertos" value={open} tone="status-err" />
        <Stat label="Críticos" value={critical} tone="status-warn" />
        <Stat label="Total de violações" value={num(stats.by_status)} />
        <Stat label="Reincidentes" value={stats.top_offenders.length} />
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="card p-5">
          <h3 className="font-semibold mb-4">Violações por tipo de asset</h3>
          {stats.by_capability.length === 0 && <p className="text-text-dim text-sm">Nenhuma violação registrada.</p>}
          <div className="space-y-2">
            {stats.by_capability.map((c) => {
              const max = Math.max(...stats.by_capability.map((x) => Number(x.n)));
              return (
                <div key={c.capability} className="flex items-center gap-3">
                  <div className="w-32 text-sm text-text-dim truncate">{c.capability}</div>
                  <div className="flex-1 h-2 bg-navy-800 rounded-full overflow-hidden">
                    <div className="h-full bg-lava rounded-full" style={{ width: `${(Number(c.n) / max) * 100}%` }} />
                  </div>
                  <div className="w-8 text-right text-sm">{c.n}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Top reincidentes</h3>
            <button onClick={onGoAlerts} className="text-xs text-lava hover:underline">ver alertas →</button>
          </div>
          {stats.top_offenders.length === 0 && <p className="text-text-dim text-sm">Ninguém em aberto. 🎉</p>}
          <div className="space-y-2">
            {stats.top_offenders.map((o) => (
              <div key={o.principal} className="flex items-center justify-between text-sm">
                <span className="truncate text-text">{o.principal}</span>
                <span className="badge bg-status-err/15 text-status-err">{o.n}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {!workspaceId && stats.by_workspace.length > 0 && (
        <div className="card p-5">
          <h3 className="font-semibold mb-1">Workspaces com mais violações em aberto</h3>
          <p className="text-text-dim text-xs mb-4">Clique para ver os alertas do workspace.</p>
          <div className="space-y-2">
            {stats.by_workspace.map((w) => {
              const max = Math.max(...stats.by_workspace.map((x) => Number(x.n)));
              return (
                <button key={w.workspace_id} onClick={() => onPickWorkspace(w.workspace_id)}
                  className="w-full flex items-center gap-3 text-left hover:bg-surface-2 rounded-lg px-2 py-1">
                  <div className="w-64 text-sm text-text truncate">{wsLabel(w.workspace_id, w.workspace_name)}</div>
                  <div className="flex-1 h-2 bg-navy-800 rounded-full overflow-hidden">
                    <div className="h-full bg-lava rounded-full" style={{ width: `${(Number(w.n) / max) * 100}%` }} />
                  </div>
                  <div className="w-12 text-right text-sm">{w.n}</div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
