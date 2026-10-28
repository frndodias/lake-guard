import { useEffect, useState } from "react";
import { api } from "../api";
import type { EffectivePermission, User } from "../types";
import { Spinner } from "../ui";

export function UsersView({ workspaceId }: { workspaceId: string }) {
  const [users, setUsers] = useState<User[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<User | null>(null);
  const [perms, setPerms] = useState<EffectivePermission[] | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [permLoading, setPermLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api.users(search || undefined).then(setUsers).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const select = (u: User) => {
    setSelected(u); setPerms(null); setPermLoading(true);
    api.effective(u.email, workspaceId || undefined)
      .then((r) => { setPerms(r.permissions); setGroups(r.groups); })
      .catch(() => setPerms([]))
      .finally(() => setPermLoading(false));
  };
  useEffect(() => { if (selected) select(selected); }, [workspaceId]);

  return (
    <div className="grid lg:grid-cols-2 gap-6">
      <div className="card p-0 overflow-hidden">
        <div className="p-4 border-b border-border flex gap-2">
          <input className="input flex-1" placeholder="Buscar por nome ou e-mail…"
            value={search} onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()} />
          <button className="btn-primary" onClick={load}>Buscar</button>
        </div>
        <div className="max-h-[70vh] overflow-auto">
          {loading ? (
            <div className="p-6 flex items-center gap-2 text-text-dim"><Spinner className="w-5 h-5" /> Carregando…</div>
          ) : (
            users.map((u) => (
              <button key={u.id} onClick={() => select(u)}
                className={`w-full text-left px-4 py-3 border-b border-border/60 hover:bg-surface-2 ${selected?.id === u.id ? "bg-surface-2" : ""}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-text truncate">{u.name}</span>
                  <span className="flex gap-1 shrink-0">
                    {u.source === "account" && (
                      <span className="badge bg-status-info/15 text-status-info" title="Visto no audit de outro(s) workspace(s) da account">
                        account{u.n_workspaces ? ` · ${u.n_workspaces} ws` : ""}
                      </span>
                    )}
                    {!u.active && <span className="badge bg-status-mute/15 text-status-mute">inativo</span>}
                  </span>
                </div>
                <div className="text-text-dim text-xs">{u.email}</div>
              </button>
            ))
          )}
          {!loading && users.length === 0 && <div className="p-6 text-text-dim text-sm">Nenhum usuário.</div>}
        </div>
      </div>

      <div className="card p-5">
        {!selected ? (
          <p className="text-text-dim text-sm">Selecione um usuário para ver as permissões efetivas.</p>
        ) : (
          <>
            <div className="mb-4">
              <div className="text-lg font-semibold text-text">{selected.name}</div>
              <div className="text-text-dim text-sm">{selected.email}</div>
              <div className="text-text-dim text-xs mt-1">
                Permissões {workspaceId ? `no workspace ${workspaceId}` : "válidas na account inteira"} (troque no filtro do topo)
              </div>
              {groups.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {groups.map((g) => <span key={g} className="badge bg-navy-600 text-oat-dim">{g}</span>)}
                </div>
              )}
            </div>
            {permLoading ? (
              <div className="flex items-center gap-2 text-text-dim"><Spinner className="w-5 h-5" /> Resolvendo…</div>
            ) : (
              <div className="space-y-1.5">
                {perms?.map((p) => (
                  <div key={p.capability} className="flex items-center justify-between py-1.5 border-b border-border/50">
                    <span className="text-sm text-text">{p.label}</span>
                    {p.allowed
                      ? <span className="badge bg-status-ok/15 text-status-ok">permitido</span>
                      : p.denied
                        ? <span className="badge bg-status-err/15 text-status-err">negado</span>
                        : <span className="badge bg-status-mute/15 text-status-mute">sem acesso</span>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
