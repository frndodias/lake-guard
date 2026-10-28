import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { ChangeRequest } from "../types";
import {
  Card, Empty, ErrorBox, ImpactView, Loading, PlanList, SensBadge, StatusBadge, Tabs, fmtDate, go, useAsync, type Route,
} from "../ui";

type Tab = "new" | "to_approve" | "mine" | "all" | "item";

const KIND: Record<string, string> = {
  access_request: "Acesso a dado restrito", membership_add: "Entrar em persona", membership_remove: "Remover de persona",
  persona_update: "Mudança de persona", gap_fix: "Alinhar ao modelo", migration_wave: "Onda de migração",
  migration_rollback: "Rollback de onda", alert_fix: "Correção de alerta",
};

export function RequestsView({ route }: { route: Route }) {
  const { me } = useApp();
  const tab = (["new", "to_approve", "mine", "all", "item"].includes(route.a || "") ? route.a : "new") as Tab;
  return (
    <div>
      <Tabs<Tab> value={tab === "item" ? "all" : tab} onChange={(t) => go("requests", t)} tabs={[
        { id: "new", label: "Pedir acesso" },
        { id: "to_approve", label: `Para eu aprovar${me.badges.pending ? ` (${me.badges.pending})` : ""}` },
        { id: "mine", label: "Minhas solicitações" },
        ...(me.can_view ? [{ id: "all" as Tab, label: "Todas" }] : []),
      ]} />
      {tab === "new" && <NewRequest />}
      {(tab === "to_approve" || tab === "mine" || tab === "all") && <RequestList scope={tab} />}
      {tab === "item" && route.b && <SingleRequest id={Number(route.b)} />}
    </div>
  );
}

function NewRequest() {
  const { me, notify, refreshMe } = useApp();
  const { data, error, loading } = useAsync(() => api.requestTargets(), []);
  const [type, setType] = useState<"clearance" | "persona">("clearance");
  const [target, setTarget] = useState("");
  const [member, setMember] = useState("");
  const [days, setDays] = useState(30);
  const [just, setJust] = useState("");
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const opts = type === "clearance" ? data.clearance.map((c) => ({ v: c.code, l: `${c.name} (${c.group})`, c }))
    : data.personas.map((p) => ({ v: p.code, l: `${p.code} — ${p.label}`, c: null }));
  const chosen = data.clearance.find((c) => c.code === target);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.requestAccess({ target_type: type, target, member_id: member || null, duration_days: days, justification: just });
      notify(`Solicitação #${r.id} criada`); refreshMe(); go("requests", "item", String(r.id));
    } catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  return (
    <div className="grid lg:grid-cols-3 gap-5">
      <Card className="lg:col-span-2" title="Pedir acesso com prazo"
        subtitle="Quem decide não executa: o steward do domínio aprova (e o DPO, se for crítico); o SP do app adiciona você ao grupo e remove no fim do prazo.">
        <div className="space-y-4">
          <div className="flex gap-2">
            {(["clearance", "persona"] as const).map((t) => (
              <button key={t} className={type === t ? "btn-primary" : "btn-ghost"} onClick={() => { setType(t); setTarget(""); }}>
                {t === "clearance" ? "Dado restrito (clearance)" : "Entrar numa persona"}
              </button>
            ))}
          </div>
          <select className="input w-full" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">{type === "clearance" ? "Domínio…" : "Persona…"}</option>
            {opts.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
          </select>
          {chosen && (
            <div className="text-xs text-text-dim flex items-center gap-2">
              <SensBadge s={chosen.sensitivity} />
              {chosen.requires_dpo ? "Domínio crítico: precisa do steward e do DPO." : "Aprovação do steward do domínio."}
              {!chosen.exists && <span className="text-status-err">grupo {chosen.group} não existe</span>}
            </div>
          )}
          {me.is_admin && (
            <select className="input w-full" value={member} onChange={(e) => setMember(e.target.value)}>
              <option value="">Para mim ({me.email})</option>
              {data.people.map((p) => <option key={p.id} value={p.id}>Em nome de: {p.label}</option>)}
            </select>
          )}
          <div className="flex items-center gap-3 text-sm">
            <span>Prazo</span>
            {[7, 30, 90].map((d) => (
              <button key={d} className={days === d ? "btn-primary !py-1" : "btn-ghost !py-1"} onClick={() => setDays(d)}>{d} dias</button>
            ))}
          </div>
          <textarea className="input w-full h-24" placeholder="Justificativa: para que você precisa do acesso?" value={just}
            onChange={(e) => setJust(e.target.value)} />
          <button className="btn-primary" disabled={busy || !target || just.length < 5} onClick={submit}>Enviar solicitação</button>
        </div>
      </Card>
      <Card title="Como funciona">
        <ol className="text-sm text-text-dim space-y-2 list-decimal pl-4">
          <li>Você pede acesso a um domínio restrito (ou a uma persona) com prazo e justificativa.</li>
          <li>O app mostra o impacto (o que passa a ler) para quem vai aprovar.</li>
          <li>O steward do domínio aprova. Domínios críticos (RH, fintech) também exigem o DPO.</li>
          <li>O service principal do app adiciona você ao grupo <code>clearance-*</code>; nunca há GRANT direto ao usuário.</li>
          <li>No fim do prazo o acesso é removido automaticamente. Tudo fica registrado.</li>
        </ol>
      </Card>
    </div>
  );
}

function RequestList({ scope }: { scope: string }) {
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.requests(scope, status || undefined), [scope, status]);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <select className="input !py-1.5" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Todos os status</option>
          {["pending", "applied", "rejected", "failed", "expired", "revoked", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn-ghost !py-1.5" onClick={reload}>Atualizar</button>
      </div>
      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.length === 0 && <Empty>Nenhuma solicitação.</Empty>}
      {data?.map((r) => <RequestCard key={r.id} r={r} onChange={reload} />)}
    </div>
  );
}

function SingleRequest({ id }: { id: number }) {
  const { data, error, loading, reload } = useAsync(() => api.request(id), [id]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return data ? <RequestCard r={data} onChange={reload} open /> : null;
}

export function RequestCard({ r, onChange, open = false }: { r: ChangeRequest; onChange: () => void; open?: boolean }) {
  const { notify, refreshMe } = useApp();
  const [show, setShow] = useState(open);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<ChangeRequest>, msg: string) => {
    setBusy(true);
    try { const x = await fn(); notify(`${msg} (#${x.id}: ${x.status})`); onChange(); refreshMe(); }
    catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  const failed = (r.result?.results || []).filter((x) => !x.ok);
  const stages = r.can_approve || [];
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-text-dim text-xs">#{r.id}</span>
            <StatusBadge s={r.status} />
            <span className="badge bg-surface-2 text-text-dim">{KIND[r.kind] || r.kind}</span>
            {r.requires_dpo && <span className="badge bg-status-err/15 text-status-err">exige DPO</span>}
          </div>
          <div className="font-medium mt-1">{r.title}</div>
          <div className="text-xs text-text-dim mt-1">
            por {r.requested_by} · {fmtDate(r.created_at, true)}
            {r.duration_days ? ` · prazo ${r.duration_days} dias` : ""}
            {r.expires_at ? ` · expira ${fmtDate(r.expires_at, true)}` : ""}
          </div>
          {r.justification && <div className="text-sm mt-2">“{r.justification}”</div>}
          <div className="text-xs text-text-dim mt-2 flex flex-wrap gap-3">
            <span>Aprovador: {r.approved_by || "pendente"}</span>
            {r.requires_dpo && <span>DPO: {r.dpo_approved_by || "pendente"}</span>}
            {r.rejected_by && <span className="text-status-err">rejeitado por {r.rejected_by}</span>}
            {r.decision_note && <span>nota: {r.decision_note}</span>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          {stages.length > 0 && (
            <div className="flex items-center gap-2">
              <input className="input !py-1 text-xs w-48" placeholder="nota (opcional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="btn-primary !py-1" disabled={busy} onClick={() => act(() => api.approve(r.id, note), "Aprovado")}>
                Aprovar{stages.length > 1 ? " (steward + DPO)" : stages[0] === "dpo" ? " como DPO" : ""}
              </button>
              <button className="btn-ghost !py-1" disabled={busy} onClick={() => act(() => api.reject(r.id, note), "Rejeitado")}>Rejeitar</button>
            </div>
          )}
          {r.is_mine && r.status === "pending" && (
            <button className="text-xs text-text-dim hover:underline" onClick={() => act(() => api.cancel(r.id), "Cancelado")}>cancelar</button>
          )}
          {r.status === "applied" && ["access_request", "membership_add"].includes(r.kind) && (
            <button className="text-xs text-status-err hover:underline" onClick={() => act(() => api.revoke(r.id), "Revogado")}>revogar agora</button>
          )}
          <button className="text-xs text-lava hover:underline" onClick={() => setShow(!show)}>{show ? "ocultar detalhes" : "ver plano e impacto"}</button>
        </div>
      </div>
      {failed.length > 0 && (
        <div className="mt-3 text-xs text-status-err">{failed.map((f, i) => <div key={i}>{f.op}: {f.error}</div>)}</div>
      )}
      {show && (
        <div className="grid lg:grid-cols-2 gap-4 mt-4 pt-4 border-t border-border">
          <div><div className="text-xs uppercase text-text-dim mb-2">Plano ({r.plan.length} operações)</div><PlanList plan={r.plan} /></div>
          <div><div className="text-xs uppercase text-text-dim mb-2">Impacto</div><ImpactView impact={r.impact} /></div>
        </div>
      )}
    </div>
  );
}
