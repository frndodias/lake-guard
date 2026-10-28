import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { MigrationGroup, WavePreview } from "../types";
import {
  Card, ClassBadge, Empty, ErrorBox, ImpactView, Loading, Modal, PlanList, StatusBadge, Table, Td, fmtDate, go, useAsync,
} from "../ui";

const ACTION_LABEL: Record<string, string> = {
  to_persona: "→ persona", to_clearance: "→ clearance", delete: "apagar (resíduo)", to_sp: "→ SP por ferramenta",
  shrink_to_floor: "reduzir ao piso (BROWSE)", keep: "manter",
};

export function MigrationView() {
  const { me, notify } = useApp();
  const groups = useAsync(() => api.migrationGroups(), []);
  const waves = useAsync(() => api.waves(), []);
  const [sel, setSel] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<WavePreview | null>(null);
  const [busy, setBusy] = useState(false);
  if ((groups.loading && !groups.data) || (waves.loading && !waves.data)) return <Loading />;
  if (groups.error) return <ErrorBox error={groups.error} onRetry={groups.reload} />;
  const g = groups.data!;
  const reload = () => { groups.reload(); waves.reload(); };

  const setMap = async (x: MigrationGroup, action: string, target: string | null) => {
    try { await api.setMapping(x.group, action, target); groups.reload(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const create = async () => {
    try { await api.createWave(name, sel); setSel([]); setName(""); waves.reload(); notify("Onda criada"); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const doPreview = async (id: number) => {
    setBusy(true);
    try { setPreview(await api.wavePreview(id)); } catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };
  const submit = async (id: number) => {
    try { const r = await api.submitWave(id); notify(`Onda enviada para aprovação (#${r.id})`); setPreview(null); reload(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const rollback = async (id: number) => {
    try { const r = await api.rollbackWave(id); notify(`Rollback enviado para aprovação (#${r.id})`); reload(); }
    catch (e) { notify((e as Error).message, "err"); }
  };
  const remove = async (id: number) => {
    try { await api.deleteWave(id); waves.reload(); } catch (e) { notify((e as Error).message, "err"); }
  };

  return (
    <div className="space-y-6">
      <Card title="De-para dos grupos legados" subtitle="Sugestão automática a partir dos GRANTs e da similaridade com as personas. O admin pode trocar o destino.">
        <Table head={["", "Grupo", "Classe", "Pessoas", "GRANTs", "Destino", "Justificativa", "Status"]}>
          {g.groups.map((x) => (
            <tr key={x.group}>
              <Td>{me.is_admin && <input type="checkbox" checked={sel.includes(x.group)}
                onChange={() => setSel(sel.includes(x.group) ? sel.filter((s) => s !== x.group) : [...sel, x.group])} />}</Td>
              <Td><button className="text-text hover:text-lava text-left" onClick={() => go("explore", "identity", x.group_id)}>{x.group}</button></Td>
              <Td><ClassBadge c={x.class} /></Td>
              <Td>{x.humans}</Td>
              <Td>{x.grants}</Td>
              <Td>
                {me.is_admin ? (
                  <div className="flex gap-1">
                    <select className="input !py-1 text-xs" value={x.action} onChange={(e) => setMap(x, e.target.value, null)}>
                      {g.actions.map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}
                    </select>
                    {(x.action === "to_persona" || x.action === "to_clearance") && (
                      <select className="input !py-1 text-xs" value={x.target || ""} onChange={(e) => setMap(x, x.action, e.target.value)}>
                        <option value="">…</option>
                        {(x.action === "to_persona" ? g.personas : g.domains).map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    )}
                  </div>
                ) : <span>{ACTION_LABEL[x.action]} {x.target}</span>}
                {x.mapping?.suggested === false && <div className="text-[10px] text-text-dim mt-1">editado (sugestão: {ACTION_LABEL[x.suggested_action]} {x.suggested_target || ""})</div>}
              </Td>
              <Td className="text-xs text-text-dim max-w-xs">{x.rationale}</Td>
              <Td>{x.mapping?.status && <StatusBadge s={x.mapping.status === "planned" ? "draft" : x.mapping.status === "migrated" ? "executed" : x.mapping.status} />}</Td>
            </tr>
          ))}
        </Table>
        {me.is_admin && (
          <div className="flex flex-wrap items-center gap-2 mt-4">
            <input className="input" placeholder="Nome da onda (ex.: Piloto: time de plataforma)" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-primary" disabled={!sel.length || name.length < 2} onClick={create}>Criar onda com {sel.length} grupo(s)</button>
            <span className="text-xs text-text-dim">Sugestão de ordem: piloto → consumo → técnicas → domínios sensíveis → clone por último.</span>
          </div>
        )}
      </Card>

      <Card title="Ondas" subtitle="Cada onda: prévia de impacto → aprovação → aplicação pelo SP → rollback se necessário">
        {(waves.data || []).length === 0 ? <Empty>Nenhuma onda criada.</Empty> : (
          <Table head={["#", "Onda", "Grupos", "Status", "Criada", "Executada", ""]}>
            {waves.data!.map((w) => (
              <tr key={w.id}>
                <Td>{w.wave_order}</Td>
                <Td className="text-text">{w.name}</Td>
                <Td className="text-xs text-text-dim">{w.groups.join(", ")}</Td>
                <Td><StatusBadge s={w.status} /></Td>
                <Td className="text-text-dim">{fmtDate(w.created_at)}</Td>
                <Td className="text-text-dim">{fmtDate(w.executed_at, true)}</Td>
                <Td>
                  <div className="flex gap-2 text-xs">
                    <button className="text-lava hover:underline" disabled={busy} onClick={() => doPreview(w.id)}>prévia</button>
                    {me.is_admin && ["draft", "rolled_back"].includes(w.status) && <button className="hover:underline" onClick={() => remove(w.id)}>remover</button>}
                    {me.is_admin && w.status === "executed" && <button className="text-status-err hover:underline" onClick={() => rollback(w.id)}>rollback</button>}
                    {w.status === "pending" && <button className="hover:underline" onClick={() => go("requests", "to_approve")}>aprovar</button>}
                  </div>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {preview && (
        <Modal wide title={`Prévia: ${preview.wave.name}`} onClose={() => setPreview(null)}>
          <div className="grid lg:grid-cols-2 gap-5">
            <div>
              <div className="text-xs uppercase text-text-dim mb-2">Impacto nas pessoas</div>
              <ImpactView impact={preview.impact} />
            </div>
            <div>
              <div className="text-xs uppercase text-text-dim mb-2">Operações ({preview.plan.length})</div>
              <div className="max-h-80 overflow-y-auto"><PlanList plan={preview.plan} /></div>
              {preview.notes.length > 0 && <ul className="text-xs text-status-warn mt-3 space-y-1">{preview.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
              <div className="text-xs text-text-dim mt-3">Rollback preparado: {preview.inverse.length} operações inversas.</div>
              {me.is_admin && ["draft", "rolled_back"].includes(preview.wave.status) && preview.plan.length > 0 && (
                <button className="btn-primary mt-4" onClick={() => submit(preview.wave.id)}>Enviar para aprovação</button>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
