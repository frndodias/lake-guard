import { useMemo, useState } from "react";
import type { GraphData, GraphNode } from "../types";
import { go } from "../ui";

const COLORS: Record<string, string> = {
  user: "#8FA6A9", sp: "#A78BFA", persona: "#FF3621", idp_persona: "#2272B4", clearance: "#00A972",
  legacy: "#F2A900", clone: "#FF3621", system: "#A78BFA", other: "#8FA6A9", securable: "#5B6B70",
};

function color(n: GraphNode): string {
  if (n.kind === "securable") return n.sensitivity ? "#F2A900" : COLORS.securable;
  if (n.kind === "group") return COLORS[n.class || "other"] || COLORS.other;
  return COLORS[n.kind] || COLORS.other;
}

/** Rede de acessos ao redor de um nó: anéis por distância (identidade → grupos → objetos). */
export function GraphView({ data, height = 520 }: { data: GraphData; height?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const width = 1100;
  const pos = useMemo(() => {
    const rings = new Map<number, GraphNode[]>();
    data.nodes.forEach((n) => rings.set(n.ring, [...(rings.get(n.ring) || []), n]));
    const maxRing = Math.max(...data.nodes.map((n) => n.ring), 1);
    const p: Record<string, { x: number; y: number }> = {};
    const cx = width / 2, cy = height / 2;
    const rStep = (Math.min(width, height * 1.9) / 2 - 70) / maxRing;
    rings.forEach((nodes, ring) => {
      nodes.forEach((n, i) => {
        if (ring === 0) { p[n.id] = { x: cx, y: cy }; return; }
        const a = (2 * Math.PI * i) / nodes.length + ring * 0.6;
        p[n.id] = { x: cx + Math.cos(a) * rStep * ring * 1.6, y: cy + Math.sin(a) * rStep * ring * 0.85 };
      });
    });
    return p;
  }, [data, height]);

  const linked = (id: string) => data.edges.some((e) => (e.from === hover && e.to === id) || (e.to === hover && e.from === id));

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[800px]" style={{ height }}>
        {data.edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to];
          if (!a || !b) return null;
          const hot = hover && (e.from === hover || e.to === hover);
          return (
            <g key={i}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={e.kind === "grant" ? "#FF3621" : "#8FA6A9"}
                strokeOpacity={hover ? (hot ? 0.9 : 0.08) : 0.35} strokeWidth={hot ? 2 : 1.2}
                strokeDasharray={e.kind === "grant" ? "" : "4 3"} />
              {hot && e.privileges && (
                <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} fontSize={10} textAnchor="middle" fill="currentColor"
                  className="fill-text">{e.privileges.join(", ")}</text>
              )}
            </g>
          );
        })}
        {data.nodes.map((n) => {
          const p = pos[n.id];
          if (!p) return null;
          const dim = hover && hover !== n.id && !linked(n.id);
          const r = n.ring === 0 ? 14 : n.kind === "securable" ? 7 : 9;
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer", opacity: dim ? 0.25 : 1 }}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
              onClick={() => (n.kind === "securable" ? go("explore", "asset", n.full_name) : go("explore", "identity", n.id))}>
              {n.kind === "securable"
                ? <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={2} fill={color(n)} />
                : <circle r={r} fill={color(n)} stroke={n.ring === 0 ? "#fff" : "none"} strokeWidth={2} />}
              <text y={r + 12} fontSize={10.5} textAnchor="middle" className="fill-text" fill="currentColor">
                {n.label.length > 34 ? `${n.label.slice(0, 32)}…` : n.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-3 text-[11px] text-text-dim mt-2">
        {[["usuário", COLORS.user], ["service principal", COLORS.sp], ["persona", COLORS.persona], ["IdP", COLORS.idp_persona],
          ["clearance", COLORS.clearance], ["legado", COLORS.legacy], ["objeto", COLORS.securable], ["objeto sensível", "#F2A900"]]
          .map(([l, c]) => <span key={l} className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: c }} />{l}</span>)}
        <span>· linha tracejada = membro de · linha vermelha = GRANT (passe o mouse para ver os privilégios)</span>
      </div>
    </div>
  );
}
