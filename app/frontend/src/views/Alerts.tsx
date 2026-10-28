import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { Alert } from "../types";
import { Card, Empty, ErrorBox, Loading, SeverityBadge, StatusBadge, fmtDate, go, short, useAsync } from "../ui";

export function AlertsView() {
  const { me, notify, refreshMe } = useApp();
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState("");
  const [rule, setRule] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.alerts(status, severity || undefined, rule || undefined),
    [status, severity, rule]);
  const [busy, setBusy] = useState(false);
  const evaluate = async () => {
    setBusy(true);
    try { const r = await api.evaluate(); notify(`Regras reavaliadas: ${r.open} alertas abertos`); reload(); refreshMe(); }
    catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  const set = async (a: Alert, s: string) => {
    try { await api.setAlert(a.id, s); reload(); refreshMe(); } catch (e) { notify((e as Error).message, "err"); }
  };
  const fix = async (a: Alert) => {
    try { const r = await api.fixAlert(a.id); notify(`Correção enviada para aprovação (#${r.id})`); go("requests", "item", String(r.id)); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const byRule: Record<string, number> = {};
  (data?.counts || []).forEach((c) => { byRule[c.rule] = (byRule[c.rule] || 0) + c.n; });
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <select className="input !py-1.5" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Abertos</option><option value="acknowledged">Em análise</option>
          <option value="resolved">Resolvidos</option><option value="">Todos</option>
        </select>
        <select className="input !py-1.5" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">Todas as severidades</option><option value="critical">Crítico</option>
          <option value="warning">Atenção</option><option value="info">Info</option>
        </select>
        <select className="input !py-1.5" value={rule} onChange={(e) => setRule(e.target.value)}>
          <option value="">Todas as regras</option>
          {Object.entries(data?.rules || {}).map(([k, v]) => <option key={k} value={k}>{v}{byRule[k] ? ` (${byRule[k]})` : ""}</option>)}
        </select>
        {me.is_admin && <button className="btn-ghost !py-1.5 ml-auto" disabled={busy} onClick={evaluate}>Reavaliar regras</button>}
      </div>
      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.alerts.length === 0 && <Empty>Nenhum alerta com esses filtros.</Empty>}
      <div className="space-y-2">
        {data?.alerts.map((a) => (
          <Card key={a.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge s={a.severity} />
                  <span className="badge bg-surface-2 text-text-dim">{data.rules[a.rule] || a.rule}</span>
                  <StatusBadge s={a.status} />
                  <span className="text-xs text-text-dim">desde {fmtDate(a.first_seen, true)}</span>
                </div>
                <div className="font-medium mt-1">{a.title}</div>
                <AlertDetail a={a} />
              </div>
              <div className="flex gap-2 text-xs">
                {a.principal && /^\d+$/.test(a.principal) && <button className="text-lava hover:underline" onClick={() => go("explore", "identity", a.principal!)}>ver identidade</button>}
                {a.object && a.object.includes(".") && <button className="text-lava hover:underline" onClick={() => go("explore", "asset", a.object!)}>ver objeto</button>}
                {a.fixable && me.is_admin && a.status !== "resolved" && <button className="btn-primary !py-1 !px-2 !text-xs" onClick={() => fix(a)}>corrigir</button>}
                {a.status === "open" && <button className="hover:underline" onClick={() => set(a, "acknowledged")}>em análise</button>}
                {a.status !== "resolved" && <button className="hover:underline" onClick={() => set(a, "resolved")}>resolver</button>}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function AlertDetail({ a }: { a: Alert }) {
  const d = a.detail as Record<string, unknown>;
  const lines: string[] = [];
  if (Array.isArray(d.grants)) lines.push((d.grants as { securable: string; privilege: string }[]).slice(0, 6)
    .map((g) => `${short(g.securable)}: ${g.privilege}`).join(" · ") + ((d.grants as unknown[]).length > 6 ? " …" : ""));
  if (Array.isArray(d.readers)) lines.push(`Leem sem clearance: ${(d.readers as string[]).slice(0, 8).join(", ")}${(d.readers as string[]).length > 8 ? " …" : ""}`);
  if (Array.isArray(d.people)) lines.push(`Pessoas: ${(d.people as string[]).slice(0, 8).join(", ")}`);
  if (Array.isArray(d.users)) lines.push((d.users as string[]).slice(0, 10).join(", "));
  if (Array.isArray(d.personas)) lines.push(`Personas: ${(d.personas as string[]).join(", ") || "nenhuma"}`);
  if (typeof d.note === "string") lines.push(d.note);
  if (typeof d.hint === "string") lines.push(d.hint);
  if (!lines.length) return null;
  return <div className="text-xs text-text-dim mt-1 space-y-0.5">{lines.map((l, i) => <div key={i}>{l}</div>)}</div>;
}
