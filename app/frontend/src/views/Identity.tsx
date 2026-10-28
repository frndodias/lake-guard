import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { IdentityDetail } from "../types";
import {
  Card, ClassBadge, Empty, ErrorBox, Icon, Loading, MiniStat, PathView, Privs, SensBadge, SeverityBadge, Table, Tabs,
  Td, fmtDate, go, short, useAsync,
} from "../ui";
import { GraphView } from "./Graph";

type Tab = "access" | "canuse" | "usage" | "creations" | "groups" | "graph" | "members" | "grants";

export function IdentityView({ id, embedded = false }: { id: string; embedded?: boolean }) {
  const { data, error, loading, reload } = useAsync(() => api.identity(id), [id]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  return <IdentityBody d={data} id={id} embedded={embedded} />;
}

export function IdentityBody({ d, id, embedded }: { d: IdentityDetail; id: string; embedded?: boolean }) {
  const { me } = useApp();
  const isGroup = d.principal.type === "group";
  const [tab, setTab] = useState<Tab>(isGroup ? "members" : "access");
  const tabs: { id: Tab; label: string }[] = isGroup
    ? [{ id: "members", label: `Membros (${d.members?.length ?? 0})` }, { id: "grants", label: "GRANTs e uso" },
       { id: "groups", label: "Grupos pai" }, { id: "graph", label: "Rede de acessos" }]
    : [{ id: "access", label: "Acessos e por quê" }, { id: "canuse", label: "Pode × usa" },
       { id: "usage", label: `Uso (${d.usage?.length ?? 0})` }, { id: "creations", label: `Criou (${d.creations?.length ?? 0})` },
       { id: "groups", label: `Grupos (${d.groups.length})` }, { id: "graph", label: "Rede de acessos" }];
  const cvu = d.can_vs_use;
  return (
    <div className="space-y-5">
      {!embedded && (
        <button className="text-xs text-text-dim hover:text-text flex items-center gap-1" onClick={() => window.history.back()}>
          <Icon.Back className="w-3.5 h-3.5" /> voltar
        </button>
      )}
      <div className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-semibold">{d.principal.label}</h2>
              <ClassBadge c={d.principal.class} />
              {d.principal.active === false && !me.flags.demo_mode && (
                <span className="badge bg-status-err/15 text-status-err" title="Usuário inativo na conta">inativo</span>
              )}
            </div>
            <div className="text-xs text-text-dim mt-1">{d.principal.name}</div>
            {!isGroup && (
              <div className="flex flex-wrap gap-1 mt-2">
                {(d.personas || []).length === 0 && <span className="badge bg-status-warn/15 text-status-warn">sem persona</span>}
                {(d.personas || []).map((p) => (
                  <button key={p} className="badge bg-lava/15 text-lava" onClick={() => go("personas", p)}>{p}</button>
                ))}
                {(d.personas || []).length > 1 && <span className="badge bg-status-err/15 text-status-err">mais de uma persona</span>}
              </div>
            )}
            {isGroup && d.mapping && (
              <div className="text-xs text-text-dim mt-2">Migração: <b className="text-text">{d.mapping.action}</b>
                {d.mapping.target ? ` → ${d.mapping.target}` : ""} · {d.mapping.rationale}</div>
            )}
          </div>
          {cvu && (
            <div className="grid grid-cols-4 gap-2 min-w-[420px]">
              <MiniStat label="Pode ler" value={cvu.readable} />
              <MiniStat label="Usou (90d)" value={cvu.used} />
              <MiniStat label="Pode e não usa" value={cvu.unused} tone={cvu.unused ? "status-warn" : "text"} />
              <MiniStat label="Sensíveis" value={cvu.sensitive_readable} tone={cvu.sensitive_readable ? "status-err" : "text"} />
            </div>
          )}
        </div>
        {d.alerts.length > 0 && (
          <div className="mt-4 space-y-1">
            {d.alerts.map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-sm"><SeverityBadge s={a.severity} />{a.title}</div>
            ))}
          </div>
        )}
        {(d.manual_memberships || []).length > 0 && (
          <div className="mt-3 text-xs text-text-dim">
            Membro manual (com prazo): {d.manual_memberships!.map((m) => `${m.group_name} até ${fmtDate(m.expires_at)}`).join(" · ")}
          </div>
        )}
      </div>

      <Tabs<Tab> tabs={tabs} value={tab} onChange={setTab} />

      {tab === "access" && (
        <Card title="De onde vem cada acesso" subtitle="GRANT direto ou via grupo (inclusive aninhado). Um GRANT no catalog vale para tudo abaixo dele.">
          {(d.grants || []).length === 0 ? <Empty>Sem GRANTs.</Empty> : (
            <Table head={["Objeto", "Privilégios", "Via", "Caminho", "Alcance"]}>
              {d.grants!.map((g, i) => (
                <tr key={i}>
                  <Td>
                    <button className="text-text hover:text-lava text-left" onClick={() => go("explore", "asset", g.securable)}>{g.securable}</button>
                    <div className="text-xs text-text-dim">{g.sec_type} <SensBadge s={g.sensitivity} /></div>
                  </Td>
                  <Td><Privs list={g.privileges} /></Td>
                  <Td>{g.direct ? <span className="badge bg-status-err/15 text-status-err">GRANT direto</span> : (
                    <span className="inline-flex items-center gap-1"><ClassBadge c={g.via.class} />
                      <button className="hover:text-lava" onClick={() => go("explore", "identity", g.via.id)}>{g.via.label}</button></span>
                  )}</Td>
                  <Td><PathView start={d.principal.label} path={g.path} /></Td>
                  <Td className="text-text-dim">{g.tables} tabela(s)</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "canuse" && (
        <Card title="Tabelas que pode ler × uso real (90 dias)" subtitle="O que pode e não usa é candidato a revogação segura.">
          <Table head={["Tabela", "Sensibilidade", "Leituras 90d", "Último uso", "Acesso vem de"]}>
            {(d.readable || []).map((r) => (
              <tr key={r.table}>
                <Td><button className="text-text hover:text-lava" onClick={() => go("explore", "asset", r.table)}>{short(r.table)}</button>
                  <div className="text-[11px] text-text-dim">{r.table.split(".")[0]}</div></Td>
                <Td><SensBadge s={r.sensitivity} /></Td>
                <Td>{r.reads_90d ? r.reads_90d : <span className="badge bg-status-mute/15 text-status-mute">não usa</span>}</Td>
                <Td className="text-text-dim">{fmtDate(r.last_used)}</Td>
                <Td className="text-xs text-text-dim">{r.via}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      {tab === "usage" && (
        <Card title="O que mais acessa" subtitle="Leituras e escritas agregadas (system.access.table_lineage + uso simulado da demo).">
          {(d.usage || []).length === 0 ? <Empty>Sem uso registrado.</Empty> : (
            <Table head={["Tabela", "Ação", "Eventos", "Último", "Tem acesso hoje?", "Fonte"]}>
              {d.usage!.map((u, i) => (
                <tr key={i}>
                  <Td>{short(u.securable)} <SensBadge s={u.sensitivity} /></Td>
                  <Td>{u.action === "write" ? <span className="text-status-warn">escrita</span> : "leitura"}</Td>
                  <Td>{u.n}</Td>
                  <Td className="text-text-dim">{fmtDate(u.last_day)}</Td>
                  <Td>{u.has_access ? <Icon.Check className="w-4 h-4 text-status-ok" /> : <Icon.X className="w-4 h-4 text-status-err" />}</Td>
                  <Td className="text-xs text-text-dim">{u.source === "demo" ? "simulado" : "real"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "creations" && (
        <Card title="Assets criados" subtitle="Dashboards, jobs, Genie, clusters… (audit log)">
          {(d.creations || []).length === 0 ? <Empty>Nenhuma criação no período.</Empty> : (
            <Table head={["Quando", "Tipo", "Nome", "Onde", "Fonte"]}>
              {d.creations!.map((c, i) => (
                <tr key={i}>
                  <Td className="text-text-dim">{fmtDate(c.event_time, true)}</Td>
                  <Td>{c.capability}</Td>
                  <Td>{c.asset_name || "—"}</Td>
                  <Td className="text-text-dim">{c.location || c.workspace_id}</Td>
                  <Td className="text-xs text-text-dim">{c.source === "demo" ? "simulado" : "real"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "groups" && (
        <Card title={isGroup ? "Grupos dos quais este grupo é membro" : "Grupos (diretos e herdados)"}>
          {d.groups.length === 0 ? <Empty>Nenhum grupo.</Empty> : (
            <Table head={["Grupo", "Classe", "Nível", "Caminho"]}>
              {d.groups.map((g) => (
                <tr key={g.id} className="cursor-pointer" onClick={() => go("explore", "identity", g.id)}>
                  <Td className="text-text">{g.label}</Td>
                  <Td><ClassBadge c={g.class} /></Td>
                  <Td>{g.depth === 1 ? "direto" : `aninhado (${g.depth})`}</Td>
                  <Td><PathView start={d.principal.label} path={g.path} /></Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "members" && (
        <Card title="Membros" subtitle="Diretos e via grupos aninhados">
          {(d.members || []).length === 0 ? <Empty>Sem membros.</Empty> : (
            <Table head={["Membro", "Tipo", "Nível", "Caminho"]}>
              {d.members!.map((m) => (
                <tr key={m.id} className="cursor-pointer" onClick={() => go("explore", "identity", m.id)}>
                  <Td className="text-text">{m.label}</Td>
                  <Td><ClassBadge c={m.class} /></Td>
                  <Td>{m.depth === 1 ? "direto" : `aninhado (${m.depth})`}</Td>
                  <Td><PathView path={m.path} start={m.label} /></Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "grants" && (
        <div className="grid lg:grid-cols-2 gap-5">
          <Card title="GRANTs diretos do grupo">
            {(d.direct_grants || []).length === 0 ? <Empty>Sem GRANTs diretos.</Empty> : (
              <Table head={["Objeto", "Privilégios", "Alcance"]}>
                {d.direct_grants!.map((g, i) => (
                  <tr key={i}>
                    <Td>{g.securable} <SensBadge s={g.sensitivity} /></Td>
                    <Td><Privs list={g.privileges} /></Td>
                    <Td className="text-text-dim">{g.tables}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
          <Card title="Concede × usa" subtitle="Tabelas que o grupo libera e quanto os membros de fato leram (90d)">
            {(d.grants_vs_use || []).length === 0 ? <Empty>O grupo não libera leitura de tabelas.</Empty> : (
              <Table head={["Tabela", "Leituras dos membros"]}>
                {d.grants_vs_use!.map((g) => (
                  <tr key={g.table}>
                    <Td>{short(g.table)} <SensBadge s={g.sensitivity} /></Td>
                    <Td>{g.reads_90d || <span className="badge bg-status-mute/15 text-status-mute">ninguém usa</span>}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
      )}

      {tab === "graph" && <GraphCard id={id} />}
    </div>
  );
}

function GraphCard({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => api.graph(id), [id]);
  return (
    <Card title="Rede de acessos" subtitle="Identidade no centro → grupos (diretos e aninhados) → objetos com GRANT. Clique para navegar.">
      {loading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && <GraphView data={data} />}
    </Card>
  );
}
