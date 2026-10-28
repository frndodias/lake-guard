import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { Domain } from "../types";
import { Card, ErrorBox, Loading, Modal, SensBadge, Table, Td, go, useAsync } from "../ui";

export function DomainsView() {
  const { me, notify } = useApp();
  const { data, error, loading, reload } = useAsync(() => api.domains(), []);
  const [edit, setEdit] = useState<Partial<Domain> | null>(null);
  const [steward, setSteward] = useState<Record<string, string>>({});
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const save = async () => {
    try {
      await api.saveDomain({ code: edit!.code, name: edit!.name, schema_name: edit!.schema_name, owner: edit!.owner || null,
        sensitivity: edit!.sensitivity || "normal", clearance_group: edit!.clearance_group || null, description: edit!.description || null });
      notify("Domínio salvo"); setEdit(null); reload();
    } catch (e) { notify((e as Error).message, "err"); }
  };
  const clearance = async (code: string) => {
    try { const r = await api.applyClearance(code); notify(`Solicitação #${r.id} criada`); reload(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const addSteward = async (code: string) => {
    try { await api.addSteward(code, steward[code]); setSteward({ ...steward, [code]: "" }); reload(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const rmSteward = async (code: string, p: string) => {
    try { await api.removeSteward(code, p); reload(); } catch (e) { notify((e as Error).message, "err"); }
  };
  return (
    <div className="space-y-6">
      {data.unregistered_schemas.length > 0 && (
        <div className="card p-4 border-status-warn/40 text-sm">
          <b className="text-status-warn">Schemas de domínio sem cadastro:</b> {data.unregistered_schemas.join(", ")}.
          {" "}Enquanto não forem classificados, nenhuma persona recebe GRANT neles.
          {me.is_admin && data.unregistered_schemas.map((s) => (
            <button key={s} className="ml-2 text-lava hover:underline"
              onClick={() => setEdit({ code: s.replace(/^data_/, ""), name: s.replace(/^data_/, ""), schema_name: s, sensitivity: "normal" })}>
              cadastrar {s}
            </button>
          ))}
        </div>
      )}
      <Card title="Domínios da camada product" subtitle="Sensibilidade define quem acessa: normal → personas; restrito/crítico → só com clearance (crítico exige DPO)."
        right={me.is_admin && <button className="btn-ghost !py-1.5" onClick={() => setEdit({ sensitivity: "normal" })}>Novo domínio</button>}>
        <Table head={["Domínio", "Schema", "Sensibilidade", "Tabelas", "Clearance", "Stewards (aprovadores)", ""]}>
          {data.domains.map((d) => (
            <tr key={d.code}>
              <Td><div className="text-text">{d.name}</div><div className="text-xs text-text-dim">{d.owner || "sem dono"}</div></Td>
              <Td><button className="font-mono text-xs hover:text-lava" onClick={() => go("explore", "asset", d.schema_full_name)}>{d.schema_name}</button>
                {!d.schema_exists && <div className="text-[10px] text-status-err">schema não existe</div>}</Td>
              <Td>{d.sensitivity === "normal" ? <span className="badge bg-status-mute/15 text-status-mute">normal</span> : <SensBadge s={d.sensitivity} />}</Td>
              <Td>{d.tables}{d.sensitive_tables ? <span className="text-xs text-text-dim"> ({d.sensitive_tables} marcadas)</span> : ""}</Td>
              <Td>
                {d.clearance_physical ? (
                  <div>
                    <div className="font-mono text-xs">{d.clearance_physical}</div>
                    <div className="text-xs text-text-dim">{d.clearance_exists ? `${d.clearance_members.length} membro(s)` : "grupo não existe"}</div>
                    {d.clearance_plan.length > 0 && (
                      <div className="mt-1">
                        <span className="badge bg-status-warn/15 text-status-warn">{d.clearance_plan.length} GRANT(s) faltando</span>
                        {me.is_admin && <button className="text-xs text-lava hover:underline ml-2" onClick={() => clearance(d.code)}>aplicar</button>}
                      </div>
                    )}
                  </div>
                ) : <span className="text-text-dim text-xs">—</span>}
              </Td>
              <Td>
                <div className="space-y-1">
                  {d.stewards.map((s) => (
                    <div key={s} className="text-xs flex items-center gap-2">{s}
                      {me.is_admin && <button className="text-status-err" onClick={() => rmSteward(d.code, s)}>×</button>}</div>
                  ))}
                  {me.is_admin && (
                    <div className="flex gap-1">
                      <input className="input !py-0.5 text-xs w-40" placeholder="e-mail" value={steward[d.code] || ""}
                        onChange={(e) => setSteward({ ...steward, [d.code]: e.target.value })} />
                      <button className="btn-ghost !py-0.5 !px-2 text-xs" disabled={!steward[d.code]} onClick={() => addSteward(d.code)}>+</button>
                    </div>
                  )}
                </div>
              </Td>
              <Td>{me.is_admin && <button className="text-xs text-lava hover:underline" onClick={() => setEdit(d)}>editar</button>}</Td>
            </tr>
          ))}
        </Table>
      </Card>
      {edit && (
        <Modal title={edit.code ? `Domínio ${edit.code}` : "Novo domínio"} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {(["code", "name", "schema_name", "owner", "clearance_group", "description"] as const).map((k) => (
              <label key={k} className="space-y-1">
                <span className="text-xs text-text-dim">{{ code: "código", name: "nome", schema_name: "schema", owner: "dono (e-mail)",
                  clearance_group: "grupo de clearance (sem prefixo)", description: "descrição" }[k]}</span>
                <input className="input w-full" value={(edit[k] as string) || ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
              </label>
            ))}
            <label className="space-y-1">
              <span className="text-xs text-text-dim">sensibilidade</span>
              <select className="input w-full" value={edit.sensitivity || "normal"} onChange={(e) => setEdit({ ...edit, sensitivity: e.target.value })}>
                <option value="normal">normal (personas)</option><option value="restricted">restrito (clearance)</option>
                <option value="critical">crítico (clearance + DPO)</option>
              </select>
            </label>
          </div>
          <button className="btn-primary mt-4" disabled={!edit.code || !edit.name || !edit.schema_name} onClick={save}>Salvar</button>
        </Modal>
      )}
    </div>
  );
}
