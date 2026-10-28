import { useState } from "react";
import { api } from "../api";
import type { AssetNode, IdentityRow } from "../types";
import {
  ClassBadge, Empty, ErrorBox, Icon, Loading, SensBadge, Table, Tabs, Td, fmtDate, go, useAsync, type Route,
} from "../ui";
import { IdentityView } from "./Identity";
import { AssetView } from "./Asset";

type Tab = "users" | "sps" | "groups" | "assets";

export function ExploreView({ route }: { route: Route }) {
  if (route.a === "identity" && route.b) return <IdentityView id={route.b} />;
  if (route.a === "asset" && route.b) return <AssetView name={route.b} />;
  const tab = (["users", "sps", "groups", "assets"].includes(route.a || "") ? route.a : "users") as Tab;
  return (
    <div>
      <Tabs<Tab> value={tab} onChange={(t) => go("explore", t)} tabs={[
        { id: "users", label: "Usuários" }, { id: "sps", label: "Service principals" },
        { id: "groups", label: "Grupos" }, { id: "assets", label: "Dados (catalog → schema → tabela)" },
      ]} />
      {tab === "assets" ? <AssetsTree /> : <IdentityList type={tab === "users" ? "user" : tab === "sps" ? "sp" : "group"} />}
    </div>
  );
}

function IdentityList({ type }: { type: string }) {
  const [q, setQ] = useState("");
  const [cls, setCls] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.identities(type), [type]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const rows = (data || []).filter((r) => (!q || r.label.toLowerCase().includes(q.toLowerCase()))
    && (!cls || r.class === cls) && (type !== "user" || r.in_scope !== false));
  const classes = Array.from(new Set((data || []).map((r) => r.class || ""))).filter(Boolean);
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1 max-w-md">
          <Icon.Search className="w-4 h-4 absolute left-3 top-2.5 text-text-dim" />
          <input className="input w-full !pl-9" placeholder="Buscar por nome ou e-mail" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {type === "group" && (
          <select className="input" value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="">Todas as classes</option>
            {classes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
      </div>
      {type === "group" ? <GroupTable rows={rows} /> : <PeopleTable rows={rows} />}
    </div>
  );
}

function PeopleTable({ rows }: { rows: IdentityRow[] }) {
  if (!rows.length) return <Empty>Nenhuma identidade encontrada.</Empty>;
  return (
    <Table head={["Identidade", "Persona", "Grupos", "Tabelas que pode ler", "Leituras 90d", "Última atividade", "Alertas"]}>
      {rows.map((r) => (
        <tr key={r.id} className="cursor-pointer" onClick={() => go("explore", "identity", r.id)}>
          <Td><div className="text-text">{r.label}</div><div className="text-xs text-text-dim">{r.name}</div></Td>
          <Td>
            {(r.personas || []).length === 0 && <span className="badge bg-status-warn/15 text-status-warn">sem persona</span>}
            {(r.personas || []).map((p) => <span key={p} className="badge bg-lava/15 text-lava mr-1">{p}</span>)}
            {(r.personas || []).length > 1 && <span className="badge bg-status-err/15 text-status-err">conflito</span>}
          </Td>
          <Td>{r.groups}</Td>
          <Td>{r.readable}</Td>
          <Td>{r.reads_90d || 0}</Td>
          <Td className="text-text-dim">{fmtDate(r.last_activity)}</Td>
          <Td>{r.alerts > 0 ? <span className="badge bg-status-err/15 text-status-err">{r.alerts}</span> : "—"}</Td>
        </tr>
      ))}
    </Table>
  );
}

function GroupTable({ rows }: { rows: IdentityRow[] }) {
  if (!rows.length) return <Empty>Nenhum grupo encontrado.</Empty>;
  return (
    <Table head={["Grupo", "Classe", "Membros diretos", "Pessoas (com aninhados)", "GRANTs diretos", "Alertas"]}>
      {rows.map((r) => (
        <tr key={r.id} className="cursor-pointer" onClick={() => go("explore", "identity", r.id)}>
          <Td className="text-text">{r.label}</Td>
          <Td><ClassBadge c={r.class} />{r.persona_code && <span className="text-xs text-text-dim ml-1">{r.persona_code}</span>}</Td>
          <Td>{r.members}</Td>
          <Td>{r.humans}</Td>
          <Td>{r.grants}</Td>
          <Td>{r.alerts > 0 ? <span className="badge bg-status-err/15 text-status-err">{r.alerts}</span> : "—"}</Td>
        </tr>
      ))}
    </Table>
  );
}

function AssetsTree() {
  const { data, error, loading, reload } = useAsync(() => api.assets(), []);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const rows: { n: AssetNode; depth: number }[] = [];
  const walk = (n: AssetNode, depth: number) => {
    rows.push({ n, depth });
    if (open[n.name]) n.children.forEach((c) => walk(c, depth + 1));
  };
  (data || []).forEach((c) => walk(c, 0));
  return (
    <Table head={["Objeto", "Tipo", "Domínio", "GRANTs diretos", "Tabelas", "Leituras 90d", "Quem leu (90d)", "Dono"]}>
      {rows.map(({ n, depth }) => (
        <tr key={n.name}>
          <Td>
            <div className="flex items-center gap-1.5" style={{ paddingLeft: depth * 18 }}>
              {n.children.length > 0 ? (
                <button className="text-text-dim w-4" onClick={() => setOpen({ ...open, [n.name]: !open[n.name] })}>
                  {open[n.name] ? "▾" : "▸"}
                </button>
              ) : <span className="w-4" />}
              <button className="text-text hover:text-lava text-left" onClick={() => go("explore", "asset", n.name)}>{n.label}</button>
              <SensBadge s={n.sensitivity} />
              {n.type !== "catalog" && n.tables > 0 && n.reads_90d === 0 && <span className="badge bg-status-mute/15 text-status-mute">sem uso</span>}
            </div>
          </Td>
          <Td className="text-text-dim">{n.type}{n.catalog_logical && n.type === "catalog" ? ` · ${n.catalog_logical}` : ""}</Td>
          <Td className="text-text-dim">{n.domain || "—"}</Td>
          <Td>{n.grants}</Td>
          <Td>{n.tables}</Td>
          <Td>{n.reads_90d}</Td>
          <Td>{n.readers_90d}</Td>
          <Td className="text-text-dim text-xs">{n.owner}</Td>
        </tr>
      ))}
    </Table>
  );
}
