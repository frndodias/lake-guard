import { useState } from "react";
import { api } from "../api";
import type { Level } from "../types";
import {
  Card, ClassBadge, ErrorBox, LEVEL_LABEL, LEVEL_STYLE, Loading, SeverityBadge, Stat, fmtDate, go, useAsync,
} from "../ui";

const CLASS_ORDER = ["persona", "clearance", "legacy", "clone", "system", "user", "sp"];
const CLASS_LABEL: Record<string, string> = {
  persona: "Personas", clearance: "Clearance", legacy: "Grupos legados", clone: "Clone de users",
  system: "Agentes / SPs", user: "Usuários (GRANT direto)", sp: "Service principals (GRANT direto)",
};

export function OverviewView() {
  const { data, error, loading, reload } = useAsync(() => api.overview(), []);
  const [filter, setFilter] = useState<string>("");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const inv = data.inventory;
  const gbc = data.identities.groups_by_class;
  const rows = data.matrix.filter((r) => !filter || r.class === filter);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between text-xs text-text-dim">
        <span>
          Inventário: {inv?.last_run_at ? fmtDate(inv.last_run_at, true) : "nunca executado"}
          {inv?.status === "error" && <span className="text-status-err"> · erro: {inv.error}</span>}
        </span>
        <button className="btn-ghost !py-1 text-xs" onClick={reload}>Atualizar</button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        <Stat label="Usuários no escopo" value={data.identities.users} hint={`${data.identities.sps} service principals`}
          onClick={() => go("explore", "users")} />
        <Stat label="Com exatamente 1 persona" value={`${data.personas.migrated_pct}%`}
          hint={`${data.personas.exactly_one} ok · ${data.personas.none} sem · ${data.personas.multiple} com várias`}
          tone={data.personas.migrated_pct < 80 ? "status-warn" : "status-ok"} />
        <Stat label="Grupos" value={data.identities.groups}
          hint={`${gbc.persona ?? 0} personas · ${gbc.legacy ?? 0} legados · ${gbc.clone ?? 0} clone`}
          onClick={() => go("explore", "groups")} />
        <Stat label="GRANTs fora do modelo" value={`${data.grants.outside_pct}%`}
          hint={`${data.grants.outside_model} de ${data.grants.total} · ${data.grants.direct_user} diretos a usuário`}
          tone={data.grants.outside_pct > 20 ? "status-err" : "text"} onClick={() => go("migration")} />
        <Stat label="Alertas abertos" value={data.alerts.open}
          hint={`${data.alerts.by_severity.critical ?? 0} críticos`}
          tone={(data.alerts.by_severity.critical ?? 0) > 0 ? "status-err" : "text"} onClick={() => go("alerts")} />
        <Stat label="Solicitações pendentes" value={data.requests_pending} onClick={() => go("requests", "to_approve")} />
      </div>

      <Card title="Matriz de acesso: quem tem GRANT direto em cada catalog"
        subtitle="Nível mais forte no catalog ou em qualquer schema/tabela dentro dele. Clique numa linha para ver a visão 360."
        right={
          <select className="input !py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Todas as classes</option>
            {CLASS_ORDER.map((c) => <option key={c} value={c}>{CLASS_LABEL[c]}</option>)}
          </select>
        }>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-text-dim">
                <th className="text-left font-medium py-2 pr-3">Principal</th>
                {data.catalogs.map((c) => (
                  <th key={c.logical} className="font-medium px-1 py-2 text-center min-w-[84px]" title={c.physical}>
                    <div>{c.logical}</div>
                    <div className="text-[10px] font-normal opacity-70">{c.env}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border hover:bg-surface-2/60 cursor-pointer"
                  onClick={() => go("explore", "identity", r.id)}>
                  <td className="py-1.5 pr-3">
                    <div className="flex items-center gap-2">
                      <ClassBadge c={r.class} />
                      <span className="text-text truncate max-w-[260px]">{r.name}</span>
                      {r.humans !== null && r.humans > 0 && <span className="text-text-dim">· {r.humans} pessoas</span>}
                    </div>
                  </td>
                  {data.catalogs.map((c) => {
                    const cell = r.cells[c.logical];
                    const lv = (cell?.level || "none") as Level;
                    return (
                      <td key={c.logical} className="px-1 py-1">
                        <div className={`rounded-md text-center py-1 ${LEVEL_STYLE[lv]}`}
                          title={cell?.privileges.join(", ") || "sem GRANT"}>
                          {LEVEL_LABEL[lv]}{cell?.schema_grants ? <span className="opacity-70"> ·{cell.schema_grants}s</span> : null}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-3 mt-3 text-[11px] text-text-dim">
          {(["browse", "read", "write", "all"] as Level[]).map((l) => (
            <span key={l} className="flex items-center gap-1"><span className={`w-3 h-3 rounded ${LEVEL_STYLE[l]}`} />{LEVEL_LABEL[l]}</span>
          ))}
          <span>· “·Ns” = N GRANTs em schemas/tabelas do catalog</span>
        </div>
      </Card>

      <div className="grid lg:grid-cols-2 gap-6">
        <Card title="Principais anomalias" right={<button className="text-xs text-lava hover:underline" onClick={() => go("alerts")}>ver todas →</button>}>
          <div className="space-y-2">
            {data.alerts.top.map((a) => (
              <div key={a.id} className="flex items-start gap-2 text-sm">
                <SeverityBadge s={a.severity} />
                <span className="text-text">{a.title}</span>
              </div>
            ))}
            {data.alerts.top.length === 0 && <p className="text-sm text-text-dim">Nenhum alerta aberto.</p>}
          </div>
        </Card>
        <Card title="Grupos por classe" subtitle="Classificação automática pelo nome e pelo modelo">
          <div className="space-y-2">
            {Object.entries(gbc).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
              const max = Math.max(...Object.values(gbc));
              return (
                <div key={k} className="flex items-center gap-3">
                  <div className="w-28"><ClassBadge c={k} /></div>
                  <div className="flex-1 h-2 bg-navy-800 rounded-full overflow-hidden">
                    <div className="h-full bg-lava rounded-full" style={{ width: `${(v / max) * 100}%` }} />
                  </div>
                  <div className="w-8 text-right text-sm">{v}</div>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-text-dim mt-4">
            Legados e clone concedem acesso por área (e não por papel). Veja o de-para em <button className="text-lava hover:underline" onClick={() => go("migration")}>Migração</button>.
          </p>
        </Card>
      </div>
    </div>
  );
}
