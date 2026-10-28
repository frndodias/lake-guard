import { useEffect, useState } from "react";
import { api } from "../api";
import type { GenieAnswer } from "../types";
import { Spinner } from "../ui";

const SUGGESTIONS = [
  "Quem criou Genie spaces sem permissão nos últimos 7 dias?",
  "Quais os 5 usuários com mais violações?",
  "Quantos dashboards foram criados sem permissão este mês?",
];

export function AgentView() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [q, setQ] = useState("");
  const [conv, setConv] = useState<string | undefined>();
  const [answer, setAnswer] = useState<GenieAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.genieStatus().then((s) => setConfigured(s.configured)).catch(() => setConfigured(false));
  }, []);

  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true); setErr(null);
    try {
      const a = await api.genieAsk(question, conv);
      setAnswer(a); setConv(a.conversation_id); setQ("");
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  if (configured === false) {
    return <div className="card p-6 text-status-warn text-sm">
      Genie não configurado. Defina <code className="text-text">GENIE_SPACE_ID</code> no app.yaml
      apontando para um space sobre <code className="text-text">fc_catalog.lakeguard.v_creation_events</code>.
    </div>;
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="btn-ghost text-xs" onClick={() => ask(s)} disabled={busy}>{s}</button>
        ))}
      </div>

      <div className="flex gap-2">
        <input className="input flex-1" placeholder="Pergunte sobre permissões e violações…"
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(q)} />
        <button className="btn-primary" onClick={() => ask(q)} disabled={busy || !q.trim()}>
          {busy && <Spinner className="w-4 h-4" />} Perguntar
        </button>
      </div>

      {err && <div className="card p-4 text-status-err text-sm">{err}</div>}

      {answer && (
        <div className="card p-5 space-y-4">
          {answer.answer && <p className="text-text whitespace-pre-wrap">{answer.answer}</p>}
          {answer.sql && (
            <pre className="bg-navy-900 border border-border rounded-lg p-3 text-xs overflow-auto text-oat-dim">{answer.sql}</pre>
          )}
          {answer.rows && answer.rows.length > 0 && (
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead className="text-text-dim text-xs uppercase">
                  <tr>{Object.keys(answer.rows[0]).map((k) => <th key={k} className="text-left px-3 py-2">{k}</th>)}</tr>
                </thead>
                <tbody>
                  {answer.rows.map((row, i) => (
                    <tr key={i} className="border-t border-border">
                      {Object.values(row).map((v, j) => <td key={j} className="px-3 py-2 text-text">{String(v)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
