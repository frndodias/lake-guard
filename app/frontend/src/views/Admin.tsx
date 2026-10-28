import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { Card, ErrorBox, Loading, Table, Tabs, Td, fmtDate, useAsync } from "../ui";

type Tab = "roles" | "inventory" | "catalogs" | "settings" | "log";

export function AdminView() {
  const [tab, setTab] = useState<Tab>("roles");
  return (
    <div>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "roles", label: "Papéis do app" }, { id: "inventory", label: "Inventário" },
        { id: "catalogs", label: "Catalogs do modelo" }, { id: "settings", label: "Configurações" },
        { id: "log", label: "Trilha de auditoria" },
      ]} />
      {tab === "roles" && <Roles />}
      {tab === "inventory" && <Inventory />}
      {tab === "catalogs" && <Catalogs />}
      {tab === "settings" && <Settings />}
      {tab === "log" && <Log />}
    </div>
  );
}

const ROLE_DESC: Record<string, string> = {
  admin: "configura personas, aprova mudanças estruturais e gerencia o app",
  steward: "aprova pedidos de acesso do seu domínio",
  dpo: "segunda aprovação em domínios críticos (RH, fintech, PII)",
  auditor: "lê tudo, não altera nada",
};

function Roles() {
  const { me, notify } = useApp();
  const { data, error, loading, reload } = useAsync(() => api.roles(), []);
  const domains = useAsync(() => api.domains(), []);
  const [f, setF] = useState({ principal: "", principal_type: "user", role: "auditor", domain: "" });
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const add = async () => {
    try { await api.addRole({ ...f, domain: f.role === "steward" ? f.domain : null }); setF({ ...f, principal: "" }); reload(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const rm = async (id: number) => { try { await api.removeRole(id); reload(); } catch (e) { notify((e as Error).message, "err"); } };
  return (
    <div className="grid lg:grid-cols-3 gap-5">
      <Card className="lg:col-span-2" title="Quem pode fazer o quê no Lakeguard" subtitle="Sem papel, a pessoa só vê o próprio acesso e pode pedir acesso.">
        <Table head={["Principal", "Papel", "Domínio", "Concedido por", ""]}>
          {(data || []).map((r) => (
            <tr key={r.id}>
              <Td>{r.principal} <span className="text-xs text-text-dim">({r.principal_type})</span></Td>
              <Td><span className="badge bg-lava/15 text-lava">{r.role}</span></Td>
              <Td>{r.domain || "—"}</Td>
              <Td className="text-xs text-text-dim">{r.granted_by} · {fmtDate(r.granted_at)}</Td>
              <Td>{me.is_admin && <button className="text-xs text-status-err hover:underline" onClick={() => rm(r.id)}>remover</button>}</Td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Adicionar papel">
        {me.is_admin ? (
          <div className="space-y-2 text-sm">
            <input className="input w-full" placeholder="e-mail ou nome do grupo" value={f.principal} onChange={(e) => setF({ ...f, principal: e.target.value })} />
            <select className="input w-full" value={f.principal_type} onChange={(e) => setF({ ...f, principal_type: e.target.value })}>
              <option value="user">usuário</option><option value="group">grupo</option>
            </select>
            <select className="input w-full" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {Object.keys(ROLE_DESC).map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <p className="text-xs text-text-dim">{ROLE_DESC[f.role]}</p>
            {f.role === "steward" && (
              <select className="input w-full" value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value })}>
                <option value="">domínio…</option>
                {(domains.data?.domains || []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
              </select>
            )}
            <button className="btn-primary" disabled={f.principal.length < 3 || (f.role === "steward" && !f.domain)} onClick={add}>Adicionar</button>
          </div>
        ) : <p className="text-sm text-text-dim">Apenas admins alteram papéis.</p>}
      </Card>
    </div>
  );
}

function Inventory() {
  const { me, notify } = useApp();
  const { data, error, loading, reload } = useAsync(() => api.inventory(), []);
  const run = async () => {
    try { const r = await api.runInventory(); notify(r.mode === "job" ? `Job disparado (run ${r.run_id})` : "Inventário iniciado"); setTimeout(reload, 1500); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const expire = async () => {
    try { const r = await api.expire(); notify(`${r.expired} acesso(s) expirado(s) processado(s)`); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const st = data!.state;
  return (
    <div className="grid lg:grid-cols-2 gap-5">
      <Card title="Inventário 360" subtitle="Identidades (SCIM de conta), objetos e GRANTs do UC, uso (lineage) e audit"
        right={me.is_admin && <button className="btn-primary !py-1.5" onClick={run}>Rodar agora</button>}>
        <div className="text-sm space-y-1">
          <div>Última execução: <b>{fmtDate(st.last_run_at, true)}</b> · status: <b className={st.status === "error" ? "text-status-err" : ""}>{st.status || "—"}</b></div>
          {st.error && <div className="text-xs text-status-err">{st.error}</div>}
          {st.counts && <div className="text-xs text-text-dim">{Object.entries(st.counts).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>}
          <div className="text-xs text-text-dim">Job: {data!.job_id || "não configurado (roda dentro do app)"}
            {data!.last_run && <> · última run: {data!.last_run.state} {data!.last_run.result || ""} — <a className="text-lava hover:underline" href={data!.last_run.url} target="_blank" rel="noreferrer">abrir</a></>}
          </div>
          {data!.inline_running && <div className="text-xs text-status-warn">rodando…</div>}
        </div>
        <button className="btn-ghost !py-1 text-xs mt-3" onClick={reload}>atualizar status</button>
      </Card>
      <Card title="Acessos temporários" subtitle="O job expira automaticamente; aqui dá para forçar agora">
        {me.is_admin && <button className="btn-ghost" onClick={expire}>Processar expirações</button>}
      </Card>
    </div>
  );
}

function Catalogs() {
  const { me, notify } = useApp();
  const { data, error, loading, reload } = useAsync(() => api.catalogs(), []);
  const [edits, setEdits] = useState<Record<string, string>>({});
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const save = async (logical: string, managed: boolean) => {
    try { await api.putCatalog(logical, edits[logical] ?? data!.find((c) => c.logical_name === logical)!.physical_name, managed); reload(); notify("Catalog atualizado"); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  return (
    <Card title="Catalogs lógicos do modelo → catalogs físicos" subtitle="O documento fala em raw, data_products_prd…; aqui se diz qual catalog real é cada um. “Gerenciado” = o app pode aplicar GRANTs.">
      <Table head={["Lógico", "Camada", "Ambiente", "Físico", "Gerenciado", ""]}>
        {(data || []).map((c) => (
          <tr key={c.logical_name}>
            <Td><div className="text-text">{c.logical_name}</div><div className="text-xs text-text-dim">{c.description}</div></Td>
            <Td>{c.layer}</Td>
            <Td>{c.env}</Td>
            <Td><input className="input !py-1 text-sm font-mono" disabled={!me.is_admin} value={edits[c.logical_name] ?? c.physical_name}
              onChange={(e) => setEdits({ ...edits, [c.logical_name]: e.target.value })} /></Td>
            <Td><input type="checkbox" checked={c.managed} disabled={!me.is_admin} onChange={() => save(c.logical_name, !c.managed)} /></Td>
            <Td>{me.is_admin && edits[c.logical_name] !== undefined && <button className="text-xs text-lava hover:underline" onClick={() => save(c.logical_name, c.managed)}>salvar</button>}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

const SETTING_HELP: Record<string, string> = {
  group_prefix: "Prefixo dos grupos do modelo na conta (demo: dbdemo-)",
  group_scope_filter: "Filtro SCIM dos grupos no escopo do inventário (vazio = todos)",
  sensitivity_tag_key: "Chave da tag que marca tabelas restritas/críticas",
  demo_mode: "Ambiente de demonstração (dados simulados)",
  allow_self_approval: "Permite aprovar o próprio pedido (só para demo!)",
  clone_group_pattern: "Trecho do nome que identifica o clone de users",
  system_groups: "Grupos de sistema/agentes (lista)",
  floor_privileges: "Piso universal por catalog lógico",
  app_principals: "Principals do próprio app (podem ter GRANTs fora do modelo)",
  audit_lookback_days: "Janela (dias) de leitura do audit log",
};

function Settings() {
  const { me, notify } = useApp();
  const { data, error, loading, reload } = useAsync(() => api.settings(), []);
  const [edits, setEdits] = useState<Record<string, string>>({});
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const save = async (k: string) => {
    try { await api.putSetting(k, JSON.parse(edits[k])); notify("Configuração salva"); const e = { ...edits }; delete e[k]; setEdits(e); reload(); }
    catch (e) { notify(`Valor inválido (JSON) ou erro: ${(e as Error).message}`, "err"); }
  };
  return (
    <Card title="Configurações" subtitle="Valores em JSON">
      <Table head={["Chave", "Valor", ""]}>
        {Object.entries(data || {}).map(([k, v]) => (
          <tr key={k}>
            <Td><div className="font-mono text-xs text-text">{k}</div><div className="text-xs text-text-dim">{SETTING_HELP[k]}</div></Td>
            <Td><input className="input w-full !py-1 text-xs font-mono" disabled={!me.is_admin} value={edits[k] ?? JSON.stringify(v)}
              onChange={(e) => setEdits({ ...edits, [k]: e.target.value })} /></Td>
            <Td>{edits[k] !== undefined && <button className="text-xs text-lava hover:underline" onClick={() => save(k)}>salvar</button>}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

function Log() {
  const { data, error, loading, reload } = useAsync(() => api.log(), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <Card title="Trilha de auditoria do app" subtitle="Quem pediu, aprovou e aplicou o quê">
      <Table head={["Quando", "Quem", "Ação", "Alvo", "Detalhe"]} dense>
        {(data || []).map((l) => (
          <tr key={l.id}>
            <Td className="text-xs text-text-dim whitespace-nowrap">{fmtDate(l.at, true)}</Td>
            <Td className="text-xs">{l.actor}</Td>
            <Td className="text-xs font-mono">{l.action}</Td>
            <Td className="text-xs">{l.target || "—"}</Td>
            <Td className="text-[11px] text-text-dim font-mono max-w-xl truncate">{JSON.stringify(l.detail)}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
