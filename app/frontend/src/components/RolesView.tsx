import { useEffect, useState } from "react";
import { api } from "../api";
import type { Capability, Grant, Workspace } from "../types";
import { Spinner, wsLabel } from "../ui";

export function RolesView({ workspaces }: { workspaces: Workspace[] }) {
  const [caps, setCaps] = useState<Capability[]>([]);
  const [principal, setPrincipal] = useState("");
  const [ptype, setPtype] = useState<"user" | "group">("user");
  const [scope, setScope] = useState("*"); // '*' = account inteira
  const [grants, setGrants] = useState<Grant[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const loadGrants = (p: string) => {
    if (!p) { setGrants([]); return; }
    api.grants(p).then(setGrants).catch(() => setGrants([]));
  };
  useEffect(() => loadGrants(principal), [principal]);

  // concessão do escopo selecionado (as de outros escopos aparecem como referência)
  const grantFor = (code: string) => grants.find((g) => g.capability === code && g.workspace_id === scope);
  const otherScopes = (code: string) => grants.filter((g) => g.capability === code && g.workspace_id !== scope);

  const setGrant = async (code: string, allowed: boolean | null) => {
    if (!principal) { setMsg("Informe um usuário (e-mail) ou grupo."); return; }
    setBusy(code); setMsg(null);
    try {
      const existing = grantFor(code);
      if (allowed === null && existing) {
        await api.deleteGrant(existing.id);
      } else if (allowed !== null) {
        await api.upsertGrant({ principal, principal_type: ptype, capability: code, workspace_id: scope, allowed });
      }
      loadGrants(principal);
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  };

  if (loading) return <div className="flex items-center gap-2 text-text-dim"><Spinner className="w-5 h-5" /> Carregando…</div>;

  return (
    <div className="space-y-5">
      <div className="card p-5 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[240px]">
          <label className="text-xs text-text-dim block mb-1">Principal (e-mail do usuário ou nome do grupo)</label>
          <input className="input w-full" placeholder="usuario@empresa.com" value={principal}
            onChange={(e) => setPrincipal(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-text-dim block mb-1">Tipo</label>
          <select className="input" value={ptype} onChange={(e) => setPtype(e.target.value as "user" | "group")}>
            <option value="user">Usuário</option>
            <option value="group">Grupo</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-text-dim block mb-1">Vale em</label>
          <select className="input max-w-[280px]" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="*">Todos os workspaces</option>
            {workspaces.map((w) => (
              <option key={w.workspace_id} value={w.workspace_id}>{wsLabel(w.workspace_id, w.workspace_name)}</option>
            ))}
          </select>
        </div>
      </div>
      <p className="text-text-dim text-xs -mt-2">
        Uma regra num workspace específico tem prioridade sobre a regra de "Todos os workspaces".
      </p>

      {msg && <div className="card p-3 text-status-err text-sm">{msg}</div>}

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy-800 text-text-dim text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Capacidade</th>
              <th className="text-left px-4 py-3">Severidade default</th>
              <th className="text-left px-4 py-3">Concessões</th>
              <th className="text-right px-4 py-3">Permissão para este principal</th>
            </tr>
          </thead>
          <tbody>
            {caps.map((c) => {
              const g = grantFor(c.code);
              const state = !g ? "none" : g.allowed ? "allow" : "deny";
              return (
                <tr key={c.code} className="border-t border-border">
                  <td className="px-4 py-3">
                    <div className="text-text">{c.label}</div>
                    <div className="text-text-dim text-xs">{c.description}</div>
                    {otherScopes(c.code).map((o) => {
                      const ws = workspaces.find((w) => w.workspace_id === o.workspace_id);
                      return (
                        <div key={o.id} className="text-xs mt-0.5">
                          <span className={o.allowed ? "text-status-ok" : "text-status-err"}>
                            {o.allowed ? "permitido" : "negado"}
                          </span>
                          <span className="text-text-dim"> em {wsLabel(o.workspace_id, ws?.workspace_name)}</span>
                        </div>
                      );
                    })}
                  </td>
                  <td className="px-4 py-3 text-text-dim">{c.default_severity}</td>
                  <td className="px-4 py-3 text-text-dim">{c.grant_count}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      {(["allow", "deny", "none"] as const).map((opt) => (
                        <button key={opt} disabled={busy === c.code || !principal}
                          onClick={() => setGrant(c.code, opt === "allow" ? true : opt === "deny" ? false : null)}
                          className={`btn !px-2.5 !py-1 text-xs ${
                            state === opt
                              ? opt === "allow" ? "bg-status-ok/20 text-status-ok"
                                : opt === "deny" ? "bg-status-err/20 text-status-err"
                                : "bg-status-mute/20 text-status-mute"
                              : "btn-ghost"
                          }`}>
                          {opt === "allow" ? "Permitir" : opt === "deny" ? "Negar" : "Herdar"}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
