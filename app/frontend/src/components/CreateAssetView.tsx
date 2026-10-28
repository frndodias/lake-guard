import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatMessage, Conversation, EffectivePermission } from "../types";
import { Icon, Spinner } from "../ui";

type Perm = EffectivePermission & { supported?: boolean };

const TOOL_LABEL: Record<string, string> = {
  execute_sql: "SQL", get_table_stats_and_schema: "Schema/stats", manage_warehouse: "Warehouses",
  list_compute: "Compute", get_current_user: "Usuário", ask_genie: "Genie",
  manage_jobs: "Job", manage_dashboard: "Dashboard", manage_pipeline: "Pipeline",
  manage_vs_endpoint: "Vector Search", manage_vs_index: "Vector Index", manage_genie: "Genie Space",
  manage_app: "App", manage_cluster: "Cluster", manage_sql_warehouse: "Warehouse",
  manage_lakebase_database: "Lakebase", manage_uc_objects: "Unity Catalog",
};

const EXAMPLES = [
  "Liste os schemas do catálogo fc_catalog",
  "Quantas tabelas tem no schema fc_catalog.ecommerce?",
  "Crie um job chamado etl-vendas que roda o notebook /Workspace/Users/fernando.custodio@databricks.com/etl",
];

function Steps({ steps }: { steps: NonNullable<ChatMessage["transcript"]> }) {
  if (!steps?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mb-2">
      {steps.map((s, i) => (
        <span key={i} className="badge bg-lava/15 text-lava" title={JSON.stringify(s.args)}>
          {TOOL_LABEL[s.tool] ?? s.tool}
        </span>
      ))}
    </div>
  );
}

export function CreateAssetView() {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [perms, setPerms] = useState<Perm[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  const loadConvs = () => api.conversations().then(setConvs).catch(() => {});
  useEffect(() => {
    loadConvs();
    api.allowedForMe().then((r) => setPerms(r.permissions)).catch(() => {});
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  const openConv = async (id: number) => {
    setActiveId(id); setErr(null);
    try { const r = await api.conversation(id); setMessages(r.messages); }
    catch (e) { setErr((e as Error).message); }
  };
  const newChat = () => { setActiveId(null); setMessages([]); setErr(null); };

  const send = async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput(""); setErr(null); setBusy(true);
    setMessages((m) => [...m, { id: Date.now(), role: "user", content: q, transcript: null, created_at: "" }]);
    try {
      const r = await api.chat(q, activeId ?? undefined);
      setActiveId(r.conversation_id);
      setMessages((m) => [...m, { id: r.message_id ?? Date.now() + 1, role: "assistant", content: r.answer, transcript: r.transcript, created_at: "" }]);
      loadConvs();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const del = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Excluir esta conversa?")) return;
    await api.deleteConversation(id).catch(() => {});
    if (activeId === id) newChat();
    loadConvs();
  };

  const startRename = (c: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(c.id); setEditTitle(c.title || "");
  };
  const saveRename = async (id: number) => {
    const t = editTitle.trim();
    setEditingId(null);
    if (!t) return;
    setConvs((cs) => cs.map((c) => (c.id === id ? { ...c, title: t } : c)));
    await api.renameConversation(id, t).catch(() => loadConvs());
  };

  const canCreate = perms.filter((p) => p.allowed && p.supported);

  return (
    <div className="grid grid-cols-[260px_1fr] gap-4 h-[calc(100vh-9rem)]">
      {/* Lista de conversas */}
      <div className="card p-0 flex flex-col overflow-hidden">
        <button onClick={newChat} className="btn-primary m-3 justify-center">
          <Icon.Plus className="w-4 h-4" /> Nova conversa
        </button>
        <div className="flex-1 overflow-auto px-2 pb-2 space-y-1">
          {convs.length === 0 && <p className="text-text-dim text-xs px-2 py-3">Nenhuma conversa ainda.</p>}
          {convs.map((c) => (
            <div key={c.id} onClick={() => editingId !== c.id && openConv(c.id)}
              className={`w-full group text-left px-3 py-2 rounded-lg flex items-center gap-2 cursor-pointer ${activeId === c.id ? "bg-surface-2" : "hover:bg-surface-2/60"}`}>
              <Icon.Chat className="w-4 h-4 text-text-dim shrink-0" />
              {editingId === c.id ? (
                <input autoFocus className="input flex-1 !py-1 !px-2 text-sm"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={() => saveRename(c.id)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveRename(c.id); if (e.key === "Escape") setEditingId(null); }}
                />
              ) : (
                <>
                  <span className="flex-1 truncate text-sm text-text">{c.title || "Conversa"}</span>
                  <span onClick={(e) => startRename(c, e)} className="opacity-0 group-hover:opacity-100 text-text-dim hover:text-lava" title="Renomear">
                    <Icon.Pencil className="w-4 h-4" />
                  </span>
                  <span onClick={(e) => del(c.id, e)} className="opacity-0 group-hover:opacity-100 text-text-dim hover:text-status-err" title="Excluir">
                    <Icon.Trash className="w-4 h-4" />
                  </span>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Thread */}
      <div className="card flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center gap-4">
              <Icon.Chat className="w-10 h-10 text-text-dim" />
              <div>
                <div className="font-semibold">Agente de criação (ai-dev-kit)</div>
                <p className="text-text-dim text-sm max-w-md mt-1">
                  Converse em linguagem natural. O agente usa as tools do ai-dev-kit (via MCP) e o gateway valida sua permissão antes de criar.
                </p>
              </div>
              {canCreate.length > 0 && (
                <div className="flex flex-wrap gap-1.5 justify-center max-w-md">
                  <span className="text-xs text-text-dim mr-1 w-full">Você pode criar:</span>
                  {canCreate.map((p) => <span key={p.capability} className="badge bg-status-ok/15 text-status-ok">{p.label}</span>)}
                </div>
              )}
              <div className="flex flex-col gap-1.5 w-full max-w-md">
                {EXAMPLES.map((ex) => (
                  <button key={ex} className="btn-ghost text-xs text-left" onClick={() => send(ex)}>{ex}</button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[80%] rounded-xl2 px-4 py-2.5 ${m.role === "user" ? "bg-lava text-white" : "bg-surface-2 text-text"}`}>
                  {m.role === "assistant" && m.transcript && <Steps steps={m.transcript} />}
                  <div className="whitespace-pre-wrap text-sm">{m.content}</div>
                </div>
              </div>
            ))
          )}
          {busy && (
            <div className="flex justify-start">
              <div className="bg-surface-2 rounded-xl2 px-4 py-2.5 flex items-center gap-2 text-text-dim text-sm">
                <Spinner className="w-4 h-4" /> O agente está trabalhando…
              </div>
            </div>
          )}
          {err && <div className="text-status-err text-sm">{err}</div>}
          <div ref={endRef} />
        </div>

        {/* Input */}
        <div className="border-t border-border p-3 flex gap-2">
          <textarea
            className="input flex-1 resize-none h-11 py-2.5"
            placeholder="Pergunte ou peça pra criar algo…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          />
          <button className="btn-primary" disabled={busy || !input.trim()} onClick={() => send()}>
            {busy ? <Spinner className="w-4 h-4" /> : "Enviar"}
          </button>
        </div>
      </div>
    </div>
  );
}
