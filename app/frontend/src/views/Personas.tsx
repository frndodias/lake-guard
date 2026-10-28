import { useEffect, useState } from "react";
import { api, type GrantRowIn } from "../api";
import { useApp } from "../App";
import type { PersonaDetail, PersonaMeta, PersonaRow, Preview } from "../types";
import {
  Card, Empty, ErrorBox, Icon, ImpactView, Loading, Modal, PERSONA_COLORS, PlanList, Priv, StatusBadge, Table, Tabs, Td,
  fmtDate, go, useAsync, type Route,
} from "../ui";

export function PersonasView({ route }: { route: Route }) {
  if (route.a) return <PersonaDetailView code={route.a} />;
  return <PersonaList />;
}

const CATS = ["Consumer", "Explorer", "Creator", "Conductor", "Platform"];

function PersonaList() {
  const { data, error, loading, reload } = useAsync(() => api.personas(), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <div className="space-y-6">
      <p className="text-sm text-text-dim max-w-4xl">
        Cada persona é um grupo de conta no Databricks (<code>persona-*</code>) que concentra os GRANTs. Os membros vêm do IdP
        (grupo <code>idp-persona-*</code> aninhado) ou são manuais, com justificativa e prazo. Toda mudança passa por prévia de
        impacto e aprovação; o service principal do app aplica.
      </p>
      {CATS.map((cat) => {
        const items = (data || []).filter((p) => p.category === cat);
        if (!items.length) return null;
        return (
          <div key={cat}>
            <h3 className="text-xs uppercase tracking-wide text-text-dim mb-2">{cat}</h3>
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
              {items.map((p) => <PersonaCard key={p.code} p={p} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PersonaCard({ p }: { p: PersonaRow }) {
  const missing = p.gap.missing || 0, extra = p.gap.extra || 0;
  return (
    <button className="card p-4 text-left hover:border-lava/50" onClick={() => go("personas", p.code)}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">{p.code}</div>
        <span className={`badge ${PERSONA_COLORS[p.category]}`}>{p.category}</span>
      </div>
      <div className="text-xs text-text-dim mt-1 line-clamp-2">{p.label}</div>
      <div className="grid grid-cols-3 gap-2 mt-3 text-center">
        <div><div className={`text-lg font-semibold ${p.people === 0 ? "text-status-warn" : ""}`}>{p.people}</div><div className="text-[10px] text-text-dim">pessoas</div></div>
        <div><div className="text-lg font-semibold">{p.via_idp}</div><div className="text-[10px] text-text-dim">via IdP</div></div>
        <div><div className="text-lg font-semibold">{p.manual}</div><div className="text-[10px] text-text-dim">manuais</div></div>
      </div>
      <div className="flex flex-wrap gap-1 mt-3">
        {!p.group_exists && <span className="badge bg-status-err/15 text-status-err">grupo inexistente</span>}
        {missing > 0 && <span className="badge bg-status-warn/15 text-status-warn">{missing} faltando</span>}
        {extra > 0 && <span className="badge bg-status-err/15 text-status-err">{extra} fora do modelo</span>}
        {p.group_exists && !missing && !extra && <span className="badge bg-status-ok/15 text-status-ok">conforme</span>}
        {p.conflicts > 0 && <span className="badge bg-status-err/15 text-status-err">{p.conflicts} com 2+ personas</span>}
      </div>
      <div className="text-[11px] text-text-dim mt-2 font-mono">{p.group}</div>
    </button>
  );
}

type Tab = "perms" | "gap" | "members" | "caps" | "history";

function PersonaDetailView({ code }: { code: string }) {
  const { me } = useApp();
  const { data, error, loading, reload } = useAsync(() => api.persona(code), [code]);
  const meta = useAsync(() => api.personaMeta(), []);
  const [tab, setTab] = useState<Tab>("gap");
  if ((loading && !data) || (meta.loading && !meta.data)) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data || !meta.data) return null;
  const p = data.persona;
  return (
    <div className="space-y-5">
      <button className="text-xs text-text-dim hover:text-text flex items-center gap-1" onClick={() => go("personas")}>
        <Icon.Back className="w-3.5 h-3.5" /> personas
      </button>
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold">{p.code}</h2>
          <span className={`badge ${PERSONA_COLORS[p.category]}`}>{p.category}</span>
          <span className="badge bg-surface-2 text-text-dim">versão {p.version}</span>
        </div>
        <div className="text-sm text-text mt-1">{p.label}</div>
        <p className="text-sm text-text-dim mt-2 max-w-4xl">{p.description}</p>
        <div className="text-xs text-text-dim mt-3 font-mono">grupo: {data.gap.group} · IdP: {String(me.flags.group_prefix || "")}{p.idp_group_name}</div>
        {data.pending.length > 0 && (
          <div className="mt-3 text-sm text-status-warn">
            {data.pending.length} mudança(s) aguardando aprovação —{" "}
            <button className="underline" onClick={() => go("requests", "to_approve")}>ver solicitações</button>
          </div>
        )}
      </div>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "gap", label: `Desejado × atual (${(data.gap.counts.missing || 0) + (data.gap.counts.extra || 0)})` },
        { id: "perms", label: "Permissões (modelo)" },
        { id: "members", label: `Membros (${data.members.people})` },
        { id: "caps", label: "O que pode criar" },
        { id: "history", label: `Histórico (${data.versions.length})` },
      ]} />
      {tab === "gap" && <GapTab d={data} onDone={reload} />}
      {tab === "perms" && <PermsTab d={data} meta={meta.data} onDone={reload} />}
      {tab === "members" && <MembersTab d={data} onDone={reload} />}
      {tab === "caps" && <CapsTab d={data} meta={meta.data} onDone={reload} />}
      {tab === "history" && <HistoryTab d={data} onDone={reload} />}
    </div>
  );
}

const GAP_STYLE: Record<string, [string, string]> = {
  ok: ["conforme", "bg-status-ok/15 text-status-ok"], missing: ["faltando", "bg-status-warn/15 text-status-warn"],
  extra: ["fora do modelo", "bg-status-err/15 text-status-err"], unmanaged: ["não gerenciado", "bg-status-mute/15 text-status-mute"],
};

function GapTab({ d, onDone }: { d: PersonaDetail; onDone: () => void }) {
  const { me, notify } = useApp();
  const [busy, setBusy] = useState(false);
  const fix = async () => {
    setBusy(true);
    try {
      const r = await api.personaFixGap(d.persona.code);
      notify(`Solicitação #${r.id} criada: aguardando aprovação`);
      onDone();
    } catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  const download = async () => {
    const txt = await api.personaScript(d.persona.code);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([txt], { type: "text/plain" }));
    a.download = `lakeguard_${d.persona.code}.sql`;
    a.click();
  };
  return (
    <div className="grid xl:grid-cols-5 gap-5">
      <Card className="xl:col-span-3" title="GRANTs do grupo da persona: modelo × Unity Catalog"
        subtitle="Desejado = matriz do documento expandida para os objetos físicos. Atual = GRANTs diretos no grupo.">
        {!d.gap.group_exists && <ErrorBox error={`O grupo ${d.gap.group} não existe na conta.`} />}
        <Table head={["Objeto", "Privilégio", "Status"]} dense>
          {d.gap.items.map((i, k) => (
            <tr key={k}>
              <Td className="font-mono text-xs">{i.securable}</Td>
              <Td><Priv p={i.privilege} /></Td>
              <Td><span className={`badge ${GAP_STYLE[i.status][1]}`}>{GAP_STYLE[i.status][0]}</span></Td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card className="xl:col-span-2" title="Plano para alinhar" subtitle="Executado pelo SP do app após aprovação"
        right={<button className="btn-ghost !py-1 text-xs" onClick={download}>exportar .sql</button>}>
        <PlanList plan={d.plan} />
        {me.is_admin && d.plan.length > 0 && (
          <button className="btn-primary mt-4 w-full justify-center" disabled={busy} onClick={fix}>
            Solicitar alinhamento ({d.plan.length} operações)
          </button>
        )}
      </Card>
    </div>
  );
}

function PermsTab({ d, meta, onDone }: { d: PersonaDetail; meta: PersonaMeta; onDone: () => void }) {
  const { me, notify } = useApp();
  const [rows, setRows] = useState<GrantRowIn[]>(() => d.grants.map((g) => ({ ...g, privileges: [...g.privileges] })));
  const [pv, setPv] = useState<Preview | null>(null);
  const [just, setJust] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setPv(null), [rows]);
  const upd = (i: number, patch: Partial<GrantRowIn>) => setRows(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const toggle = (i: number, p: string) => {
    const cur = rows[i].privileges;
    upd(i, { privileges: cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p] });
  };
  const preview = async () => {
    setBusy(true);
    try { setPv(await api.personaPreview(d.persona.code, { grants: rows })); }
    catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  const propose = async () => {
    setBusy(true);
    try {
      const r = await api.personaPropose(d.persona.code, { grants: rows, justification: just });
      notify(`Solicitação #${r.id} criada: aguardando aprovação`);
      setPv(null); onDone();
    } catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  const scopeLabel: Record<string, string> = { "": "catalog inteiro", "@staging": "schema data_staging", "@product": "schemas de domínio (product)" };
  return (
    <div className="space-y-5">
      <Card title="Permissões da persona por catalog" subtitle="Catalog lógico do modelo → físico. “Schemas de domínio” inclui só domínios cadastrados e não sensíveis; domínios restritos vão para o clearance.">
        <div className="space-y-3">
          {rows.map((r, i) => (
            <div key={i} className="border border-border rounded-lg p-3">
              <div className="flex flex-wrap items-center gap-2">
                <select className="input !py-1 text-sm" value={r.catalog} onChange={(e) => upd(i, { catalog: e.target.value })}>
                  {meta.catalogs.map((c) => <option key={c.logical} value={c.logical}>{c.logical} → {c.physical}</option>)}
                </select>
                <select className="input !py-1 text-sm" value={r.schema_scope || ""}
                  onChange={(e) => upd(i, { schema_scope: e.target.value || null })}>
                  {meta.schema_scopes.map((s) => <option key={s} value={s}>{scopeLabel[s] || s}</option>)}
                  {r.schema_scope && !meta.schema_scopes.includes(r.schema_scope) && <option value={r.schema_scope}>{r.schema_scope}</option>}
                </select>
                {!meta.catalogs.find((c) => c.logical === r.catalog)?.managed && <span className="badge bg-status-mute/15 text-status-mute">não gerenciado pelo app</span>}
                <button className="ml-auto text-xs text-status-err hover:underline" onClick={() => setRows(rows.filter((_, k) => k !== i))}>remover</button>
              </div>
              <div className="flex flex-wrap gap-1 mt-2">
                {meta.privileges.map((p) => (
                  <button key={p} onClick={() => toggle(i, p)}
                    className={`badge font-mono !text-[10px] border ${r.privileges.includes(p) ? "bg-lava/20 text-lava border-lava/40" : "border-border text-text-dim"}`}>
                    {p.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <button className="btn-ghost text-sm" onClick={() => setRows([...rows, { catalog: meta.catalogs[0].logical, schema_scope: null, privileges: [] }])}>
            <Icon.Plus className="w-4 h-4" /> adicionar linha
          </button>
        </div>
        <div className="flex gap-2 mt-4">
          <button className="btn-ghost" disabled={busy} onClick={preview}>Pré-visualizar impacto</button>
          <button className="btn-ghost" onClick={() => setRows(d.grants.map((g) => ({ ...g, privileges: [...g.privileges] })))}>Desfazer edições</button>
        </div>
      </Card>
      {pv && (
        <div className="grid xl:grid-cols-2 gap-5">
          <Card title="Impacto nas pessoas" subtitle="Quem ganha ou perde leitura, cruzado com o uso real">
            <ImpactView impact={pv.impact} />
          </Card>
          <Card title="O que muda no Unity Catalog" subtitle={`${pv.desired_added.length} privilégios a mais · ${pv.desired_removed.length} a menos no modelo`}>
            <PlanList plan={pv.plan} />
            {me.is_admin && (
              <div className="mt-4 space-y-2">
                <input className="input w-full" placeholder="Justificativa da mudança" value={just} onChange={(e) => setJust(e.target.value)} />
                <button className="btn-primary w-full justify-center" disabled={busy || just.length < 3} onClick={propose}>
                  Propor mudança (vai para aprovação)
                </button>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function MembersTab({ d, onDone }: { d: PersonaDetail; onDone: () => void }) {
  const { me, notify } = useApp();
  const targets = useAsync(() => api.requestTargets(), []);
  const [open, setOpen] = useState(false);
  const [member, setMember] = useState("");
  const [just, setJust] = useState("");
  const [days, setDays] = useState<number | "">(90);
  const add = async () => {
    try {
      const r = await api.personaAddMember(d.persona.code, { member_id: member, justification: just, duration_days: days || null });
      notify(`Solicitação #${r.id} criada`); setOpen(false); onDone();
    } catch (e) { notify((e as Error).message, "err"); }
  };
  const remove = async (id: string) => {
    try { const r = await api.personaRemoveMember(d.persona.code, id); notify(`Solicitação #${r.id} criada`); onDone(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const m = d.members;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card p-4"><div className="text-[11px] uppercase text-text-dim">Pessoas</div><div className="text-2xl font-semibold">{m.people}</div></div>
        <div className="card p-4"><div className="text-[11px] uppercase text-text-dim">Via IdP</div><div className="text-2xl font-semibold">{m.via_idp}</div></div>
        <div className="card p-4"><div className="text-[11px] uppercase text-text-dim">Manuais (com prazo)</div><div className="text-2xl font-semibold">{m.manual}</div></div>
        <div className="card p-4"><div className="text-[11px] uppercase text-text-dim">Em 2+ personas</div><div className={`text-2xl font-semibold ${m.conflicts.length ? "text-status-err" : ""}`}>{m.conflicts.length}</div></div>
      </div>
      <Card title="Membros diretos do grupo" subtitle={`${m.group} — o IdP controla os membros do grupo aninhado; os manuais passam por aprovação e expiram.`}
        right={me.is_admin && <button className="btn-primary !py-1.5" onClick={() => setOpen(true)}><Icon.Plus className="w-4 h-4" /> Adicionar membro</button>}>
        {m.direct.length === 0 ? <Empty>Sem membros — como no cliente, esta persona ainda está vazia.</Empty> : (
          <Table head={["Membro", "Origem", "Pessoas / detalhes", ""]}>
            {m.direct.map((x) => (
              <tr key={x.id}>
                <Td><button className="text-text hover:text-lava" onClick={() => go("explore", "identity", x.id)}>{x.label}</button></Td>
                <Td>
                  {x.source === "idp" && <span className="badge bg-status-info/15 text-status-info">IdP (SCIM)</span>}
                  {x.source === "manual" && <span className="badge bg-status-warn/15 text-status-warn">manual</span>}
                  {x.source === "direto" && <span className="badge bg-status-mute/15 text-status-mute">direto (fora do app)</span>}
                  {x.source === "grupo" && <span className="badge bg-status-mute/15 text-status-mute">grupo</span>}
                </Td>
                <Td className="text-xs text-text-dim">
                  {x.people ? x.people.map((p) => p.label).join(", ") || "vazio" : null}
                  {x.source === "manual" && <>“{x.justification}” · aprovado por {x.approved_by} · expira {fmtDate(x.expires_at)}</>}
                </Td>
                <Td>{me.is_admin && x.source !== "idp" && (
                  <button className="text-xs text-status-err hover:underline" onClick={() => remove(x.id)}>remover</button>
                )}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {m.conflicts.length > 0 && (
        <Card title="Pessoas em mais de uma persona" subtitle="O modelo prevê uma persona por usuário">
          <ul className="text-sm space-y-1">{m.conflicts.map((c) => <li key={c.id}>{c.label}: {c.personas.join(", ")}</li>)}</ul>
        </Card>
      )}
      {open && (
        <Modal title={`Adicionar membro manual à persona ${d.persona.code}`} onClose={() => setOpen(false)}>
          <div className="space-y-3">
            <select className="input w-full" value={member} onChange={(e) => setMember(e.target.value)}>
              <option value="">Escolha a pessoa ou service principal…</option>
              {(targets.data?.people || []).map((p) => <option key={p.id} value={p.id}>{p.label} ({p.type})</option>)}
            </select>
            <input className="input w-full" placeholder="Justificativa (obrigatória)" value={just} onChange={(e) => setJust(e.target.value)} />
            <div className="flex items-center gap-2 text-sm">
              <span>Prazo (dias)</span>
              <input className="input w-24" type="number" min={1} value={days} onChange={(e) => setDays(e.target.value ? Number(e.target.value) : "")} />
              <span className="text-text-dim text-xs">vazio = sem expiração (use com cuidado)</span>
            </div>
            <p className="text-xs text-text-dim">Membro manual é exceção: o caminho normal é o grupo do IdP. Vai para aprovação.</p>
            <button className="btn-primary" disabled={!member || just.length < 3} onClick={add}>Criar solicitação</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function CapsTab({ d, meta, onDone }: { d: PersonaDetail; meta: PersonaMeta; onDone: () => void }) {
  const { me, notify } = useApp();
  const [caps, setCaps] = useState<string[]>(d.capabilities);
  const changed = caps.slice().sort().join() !== d.capabilities.slice().sort().join();
  const save = async () => {
    try {
      const r = await api.personaPropose(d.persona.code, { capabilities: caps, justification: "Ajuste das capacidades de criação" });
      notify(`Solicitação #${r.id} criada`); onDone();
    } catch (e) { notify((e as Error).message, "err"); }
  };
  return (
    <Card title="O que esta persona pode criar" subtitle="Usado pela regra “criação sem capacidade” sobre o audit log">
      <div className="grid md:grid-cols-3 gap-2">
        {meta.capabilities.map((c) => (
          <label key={c.code} className="flex items-center gap-2 text-sm border border-border rounded-lg px-3 py-2">
            <input type="checkbox" checked={caps.includes(c.code)} disabled={!me.is_admin}
              onChange={() => setCaps(caps.includes(c.code) ? caps.filter((x) => x !== c.code) : [...caps, c.code])} />
            {c.label}
          </label>
        ))}
      </div>
      {me.is_admin && <button className="btn-primary mt-4" disabled={!changed} onClick={save}>Propor mudança</button>}
    </Card>
  );
}

function HistoryTab({ d, onDone }: { d: PersonaDetail; onDone: () => void }) {
  const { me, notify } = useApp();
  const rollback = async (v: number) => {
    try { const r = await api.personaRollback(d.persona.code, v); notify(`Rollback para v${v}: solicitação #${r.id} criada`); onDone(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  return (
    <div className="grid lg:grid-cols-2 gap-5">
      <Card title="Versões do modelo">
        <Table head={["Versão", "Quem", "Quando", ""]}>
          {d.versions.map((v) => (
            <tr key={v.version}>
              <Td>v{v.version}{v.version === d.persona.version && <span className="badge bg-status-ok/15 text-status-ok ml-2">atual</span>}</Td>
              <Td className="text-text-dim">{v.changed_by}</Td>
              <Td className="text-text-dim">{fmtDate(v.changed_at, true)}</Td>
              <Td>{me.is_admin && v.version !== d.persona.version && (
                <button className="text-xs text-lava hover:underline" onClick={() => rollback(v.version)}>voltar para esta</button>
              )}</Td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Mudanças pendentes">
        {d.pending.length === 0 ? <Empty>Nenhuma.</Empty> : (
          <ul className="space-y-2 text-sm">
            {d.pending.map((p) => (
              <li key={p.id} className="flex items-center gap-2">
                <StatusBadge s={p.status} /><button className="hover:text-lava" onClick={() => go("requests", "item", String(p.id))}>#{p.id} {p.title}</button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
