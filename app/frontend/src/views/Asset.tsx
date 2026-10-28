import { api } from "../api";
import {
  Card, ClassBadge, Empty, ErrorBox, Icon, Loading, PathView, Priv, Privs, SensBadge, Table, Td, fmtDate, go, useAsync,
} from "../ui";

export function AssetView({ name }: { name: string }) {
  const { data, error, loading, reload } = useAsync(() => api.asset(name), [name]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const s = data.securable;
  const isTable = s.type === "table" || s.type === "view";
  const noClearance = (data.readers || []).filter((r) => !r.has_clearance);
  return (
    <div className="space-y-5">
      <button className="text-xs text-text-dim hover:text-text flex items-center gap-1" onClick={() => window.history.back()}>
        <Icon.Back className="w-3.5 h-3.5" /> voltar
      </button>
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold break-all">{s.full_name}</h2>
          <span className="badge bg-surface-2 text-text-dim">{s.type}</span>
          <SensBadge s={s.sensitivity} />
          {data.unused && <span className="badge bg-status-mute/15 text-status-mute">sem uso em 90 dias</span>}
        </div>
        <div className="text-xs text-text-dim mt-2 flex flex-wrap gap-4">
          <span>dono: <b className="text-text">{s.owner || "—"}</b></span>
          <span>criado por: {s.created_by || "—"} em {fmtDate(s.created_at)}</span>
          {s.domain && <span>domínio: <b className="text-text">{s.domain}</b></span>}
          {s.catalog_logical && <span>catalog do modelo: {s.catalog_logical}</span>}
        </div>
        {isTable && s.sensitivity && (
          <div className={`mt-4 rounded-lg px-4 py-3 text-sm ${noClearance.length ? "bg-status-err/10 text-status-err" : "bg-status-ok/10 text-status-ok"}`}>
            {noClearance.length
              ? `${noClearance.length} identidade(s) conseguem ler este dado ${s.sensitivity === "critical" ? "crítico" : "restrito"} sem estar no clearance (${data.clearance_group || "nenhum clearance definido"}). GRANT no catalog inteiro alcança tabelas restritas: o bloqueio efetivo exige clearance + política ABAC ou schema dedicado.`
              : "Só identidades com clearance leem este dado."}
          </div>
        )}
      </div>

      {isTable && (
        <Card title="Quem consegue ler e por qual caminho" subtitle="Acesso efetivo: GRANT direto, via grupo (aninhado) ou herdado do schema/catalog">
          {(data.readers || []).length === 0 ? <Empty>Ninguém no escopo consegue ler.</Empty> : (
            <Table head={["Identidade", "Via", "Concedido em", "Caminho", "Clearance", "Leituras 90d"]}>
              {data.readers!.map((r) => (
                <tr key={r.id} className="cursor-pointer" onClick={() => go("explore", "identity", r.id)}>
                  <Td><span className="text-text">{r.label}</span> <ClassBadge c={r.class} /></Td>
                  <Td className="text-xs">{r.via}</Td>
                  <Td className="text-xs text-text-dim">{r.granted_on}</Td>
                  <Td><PathView start={r.label} path={r.path} /></Td>
                  <Td>{s.sensitivity ? (r.has_clearance ? <Icon.Check className="w-4 h-4 text-status-ok" />
                    : <span className="badge bg-status-err/15 text-status-err">sem clearance</span>) : "—"}</Td>
                  <Td>{r.reads_90d || "—"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="GRANTs diretos neste objeto">
          {data.direct_grants.length === 0 ? <Empty>Nenhum GRANT direto.</Empty> : (
            <Table head={["Principal", "Privilégios", "Pessoas"]}>
              {data.direct_grants.map((g, i) => (
                <tr key={i}>
                  <Td><span className="text-text">{g.principal.label}</span> <ClassBadge c={g.principal.class} /></Td>
                  <Td><Privs list={g.privileges} /></Td>
                  <Td>{g.humans ?? "—"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card title="GRANTs herdados (schema / catalog)">
          {data.inherited_grants.length === 0 ? <Empty>Nada herdado.</Empty> : (
            <Table head={["Concedido em", "Principal", "Privilégio"]}>
              {data.inherited_grants.map((g, i) => (
                <tr key={i}>
                  <Td className="text-xs text-text-dim">{g.securable}</Td>
                  <Td>{g.principal.label} <ClassBadge c={g.principal.class} /></Td>
                  <Td><Priv p={g.privilege} /></Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <Card title="Quem mais usa (90 dias)">
        {data.top_users.length === 0 ? <Empty>Sem uso registrado.</Empty> : (
          <Table head={["Identidade", "Leituras", "Último uso"]}>
            {data.top_users.map((u) => (
              <tr key={u.id} className="cursor-pointer" onClick={() => go("explore", "identity", u.id)}>
                <Td><span className="text-text">{u.label}</span> <ClassBadge c={u.class} /></Td>
                <Td>{u.n}</Td>
                <Td className="text-text-dim">{fmtDate(u.last_day)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
