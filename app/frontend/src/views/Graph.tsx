import { useEffect, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape";
import { api } from "../api";
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

/** Cor de um token CSS do tema (canais "r g b") → rgb(). */
function themeColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? `rgb(${v.split(/\s+/).join(",")})` : fallback;
}

function nodeEl(n: GraphNode, maxRing: number, position?: { x: number; y: number }): ElementDefinition {
  return {
    group: "nodes",
    data: { id: n.id, label: n.label, color: color(n), kind: n.kind, level: maxRing - n.ring + 1,
      center: n.ring === 0 && !position, full: n.full_name || "", expandable: !!n.expandable, count: n.count || 0 },
    classes: [n.kind, n.ring === 0 && !position ? "center" : "", n.expandable ? "expandable" : ""].join(" "),
    ...(position ? { position } : {}),
  };
}

const edgeId = (from: string, to: string, kind: string) => `${from}|${to}|${kind}`;

/** Zoom máximo ao enquadrar: com poucos nós o fit aproximaria demais (rótulos gigantes). */
const FIT_MAX_ZOOM = 1.4;

function capZoom(cy: Core) {
  if (cy.zoom() > FIT_MAX_ZOOM) {
    cy.zoom(FIT_MAX_ZOOM);
    cy.center();
  }
}

type Layout = "rings" | "force";

function layoutOptions(kind: Layout): LayoutOptions {
  if (kind === "force") {
    return {
      name: "cose", animate: true, animationDuration: 500, fit: true, padding: 40, randomize: false,
      nodeDimensionsIncludeLabels: true, idealEdgeLength: () => 70, nodeRepulsion: () => 4500, gravity: 0.9,
      componentSpacing: 40, nodeOverlap: 12, numIter: 1500,
    } as LayoutOptions;
  }
  return {
    name: "concentric", animate: true, animationDuration: 400, fit: true, padding: 40,
    concentric: (n: cytoscape.NodeSingular) => n.data("level"), levelWidth: () => 1,
    minNodeSpacing: 46, spacingFactor: 1.05, startAngle: (3 / 2) * Math.PI,
  } as LayoutOptions;
}

type Sel = { id: string; label: string; kind: string; full: string; expandable: boolean; count: number };

/** Rede de acessos interativa com drill-down: duplo clique expande/recolhe o nó. */
export function GraphView({ data, height = 560 }: { data: GraphData; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const origin = useRef<Set<string>>(new Set());
  const expansions = useRef<Map<string, string[]>>(new Map());
  const [layout, setLayout] = useState<Layout>("rings");
  const [selected, setSelected] = useState<Sel | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const collapse = (id: string) => {
    const cy = cyRef.current;
    const added = expansions.current.get(id);
    if (!cy || !added) return;
    // primeiro recolhe o que foi expandido a partir dos nós desta expansão
    added.filter((x) => expansions.current.has(x)).forEach(collapse);
    expansions.current.delete(id);
    const stillUsed = new Set([...expansions.current.values()].flat());
    added.filter((x) => !origin.current.has(x) && !stillUsed.has(x)).forEach((x) => cy.getElementById(x).remove());
    cy.getElementById(id).removeClass("expanded");
    setExpanded(new Set(expansions.current.keys()));
  };

  const expand = async (id: string) => {
    const cy = cyRef.current;
    if (!cy || expansions.current.has(id)) return;
    setBusy(id);
    setNote(null);
    try {
      const res = await api.graphExpand(id);
      const parent = cy.getElementById(id);
      const p = parent.position();
      const fresh = res.nodes.filter((n) => cy.getElementById(n.id).empty());
      const radius = Math.min(280, 110 + fresh.length * 7);
      const start = Math.random() * Math.PI;
      const added: string[] = [];
      cy.batch(() => {
        fresh.forEach((n, i) => {
          const a = start + (2 * Math.PI * i) / Math.max(fresh.length, 1);
          cy.add(nodeEl(n, 1, { x: p.x + Math.cos(a) * radius, y: p.y + Math.sin(a) * radius }));
          added.push(n.id);
        });
        res.edges.forEach((e) => {
          const eid = edgeId(e.from, e.to, e.kind);
          if (cy.getElementById(eid).empty() && !cy.getElementById(e.from).empty() && !cy.getElementById(e.to).empty()) {
            cy.add({ group: "edges", data: { id: eid, source: e.from, target: e.to,
              label: (e.privileges || []).join(", ").replace(/_/g, " ") }, classes: e.kind });
            added.push(eid);
          }
        });
      });
      expansions.current.set(id, added);
      parent.addClass("expanded");
      setExpanded(new Set(expansions.current.keys()));
      if (res.truncated) setNote(`${res.truncated} item(ns) a mais não exibidos — abra a página do nó para ver tudo`);
      else if (!fresh.length) setNote("Nada novo para mostrar: os vizinhos já estão na rede");
      if (fresh.length) {
        // reorganiza sem sobrepor (parte das posições atuais) e enquadra só a vizinhança expandida
        setLayout("force");
        const lay = cy.layout({ ...layoutOptions("force"), fit: false } as LayoutOptions);
        lay.one("layoutstop", () => {
          const nb = parent.closedNeighborhood().nodes();
          cy.animate({ fit: { eles: nb, padding: 70 }, duration: 350, complete: () => capZoom(cy) });
        });
        lay.run();
      }
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const toggle = (id: string) => (expansions.current.has(id) ? collapse(id) : expand(id));

  useEffect(() => {
    if (!ref.current) return;
    const text = themeColor("--text", "#1B3139");
    const dim = themeColor("--text-dim", "#5B6B70");
    const surface = themeColor("--surface", "#FFFFFF");
    const maxRing = Math.max(1, ...data.nodes.map((n) => n.ring));
    const seen = new Set<string>();
    const edges: ElementDefinition[] = [];
    data.edges.forEach((e) => {
      const id = edgeId(e.from, e.to, e.kind);
      if (seen.has(id)) return;
      seen.add(id);
      edges.push({ group: "edges", data: { id, source: e.from, target: e.to,
        label: (e.privileges || []).join(", ").replace(/_/g, " ") }, classes: e.kind });
    });
    const elements = [...data.nodes.map((n) => nodeEl(n, maxRing)), ...edges];
    origin.current = new Set(elements.map((e) => String(e.data.id)));
    expansions.current = new Map();
    setExpanded(new Set());
    const cy = cytoscape({
      container: ref.current,
      elements,
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 3,
      style: [
        { selector: "node", style: {
          "background-color": "data(color)", label: "data(label)", color: text, "font-size": 10,
          "text-valign": "bottom", "text-margin-y": 5, width: 18, height: 18, "border-width": 2,
          "border-color": surface, "text-wrap": "ellipsis", "text-max-width": "170px",
        } },
        { selector: "node.expandable", style: { "border-style": "dashed", "border-color": dim, "border-width": 2 } },
        { selector: "node.expanded", style: { "border-style": "solid", "border-color": "#FF3621", "border-width": 3 } },
        { selector: "node.center", style: { width: 34, height: 34, "font-size": 12, "font-weight": "bold", "border-color": text,
          "border-style": "solid" } },
        { selector: "node.securable", style: { shape: "round-rectangle", width: 16, height: 16 } },
        { selector: "node:selected", style: { "overlay-color": "#FF3621", "overlay-opacity": 0.15, "overlay-padding": 6 } },
        { selector: "edge", style: {
          width: 1.5, "line-color": dim, "target-arrow-color": dim, "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.8, opacity: 0.65,
        } },
        { selector: "edge.member", style: { "line-style": "dashed" } },
        { selector: "edge.contains", style: { "line-style": "dotted", "target-arrow-shape": "none", opacity: 0.5 } },
        { selector: "edge.grant", style: { "line-color": "#FF3621", "target-arrow-color": "#FF3621", width: 2 } },
        { selector: "edge.show-label", style: {
          label: "data(label)", "font-size": 9, color: text, "text-background-color": surface,
          "text-background-opacity": 0.92, "text-background-padding": "2px", "text-rotation": "autorotate", opacity: 1,
        } },
        { selector: ".faded", style: { opacity: 0.1 } },
      ],
      layout: { ...layoutOptions("rings"), animate: false } as LayoutOptions,
    });
    capZoom(cy);
    cy.on("mouseover", "node", (ev) => {
      const nb = ev.target.closedNeighborhood();
      cy.elements().not(nb).addClass("faded");
      nb.edges().addClass("show-label");
    });
    cy.on("mouseout", "node", () => cy.elements().removeClass("faded show-label"));
    cy.on("mouseover", "edge", (ev) => ev.target.addClass("show-label"));
    cy.on("mouseout", "edge", (ev) => ev.target.removeClass("show-label"));
    cy.on("tap", "node", (ev) => {
      const d = ev.target.data();
      setSelected({ id: d.id, label: d.label, kind: d.kind, full: d.full, expandable: d.expandable, count: d.count });
    });
    cy.on("tap", (ev) => { if (ev.target === cy) setSelected(null); });
    cy.on("dbltap", "node", (ev) => {
      const d = ev.target.data();
      if (d.center) return;
      if (d.expandable || expansions.current.has(d.id)) toggle(d.id);
    });
    cyRef.current = cy;
    setLayout("rings");
    return () => { cy.destroy(); cyRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const relayout = (kind: Layout) => {
    setLayout(kind);
    const cy = cyRef.current;
    if (!cy) return;
    const lay = cy.layout(layoutOptions(kind));
    lay.one("layoutstop", () => capZoom(cy));
    lay.run();
  };
  const fitAll = () => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.fit(undefined, 40);
    capZoom(cy);
  };
  const reset = () => {
    [...expansions.current.keys()].forEach(collapse);
    relayout(layout);
  };
  const exportPng = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const a = document.createElement("a");
    a.href = cy.png({ full: true, scale: 2, bg: themeColor("--surface", "#FFFFFF") });
    a.download = "rede-de-acessos.png";
    a.click();
  };
  const open = (s: Sel) => (s.kind === "securable" ? go("explore", "asset", s.full) : go("explore", "identity", s.id));
  const isOpen = selected ? expanded.has(selected.id) : false;
  const expandLabel = (s: Sel) => {
    if (s.kind === "group") return `membros (${s.count})`;
    if (s.kind === "securable") return s.count ? `conteúdo (${s.count}) e GRANTs` : "quem tem GRANT";
    return `grupos (${s.count})`;
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <div className="inline-flex rounded-lg border border-border overflow-hidden text-xs">
          {(["rings", "force"] as Layout[]).map((k) => (
            <button key={k} onClick={() => relayout(k)}
              className={`px-3 py-1.5 ${layout === k ? "bg-lava text-white" : "text-text-dim hover:bg-surface-2"}`}>
              {k === "rings" ? "Anéis" : "Força"}
            </button>
          ))}
        </div>
        <button className="btn-ghost !py-1.5 text-xs" onClick={fitAll}>Centralizar</button>
        <button className="btn-ghost !py-1.5 text-xs" onClick={() => relayout(layout)}>Reorganizar</button>
        {expanded.size > 0 && <button className="btn-ghost !py-1.5 text-xs" onClick={reset}>Recolher tudo ({expanded.size})</button>}
        <button className="btn-ghost !py-1.5 text-xs" onClick={exportPng}>Exportar PNG</button>
        {selected && (
          <span className="text-xs text-text-dim ml-auto flex items-center gap-3">
            <b className="text-text">{selected.label}</b>
            {(selected.expandable || isOpen) && selected.id !== data.nodes.find((n) => n.ring === 0)?.id && (
              <button className="text-lava hover:underline" disabled={busy === selected.id} onClick={() => toggle(selected.id)}>
                {busy === selected.id ? "carregando…" : isOpen ? "recolher" : `expandir ${expandLabel(selected)}`}
              </button>
            )}
            <button className="text-lava hover:underline" onClick={() => open(selected)}>abrir página →</button>
          </span>
        )}
      </div>
      {note && <div className="text-xs text-status-warn mb-2">{note}</div>}
      <div ref={ref} className="w-full rounded-lg border border-border bg-bg/40"
        style={{ height: `max(${height}px, calc(100vh - 380px))` }} />
      <div className="flex flex-wrap gap-3 text-[11px] text-text-dim mt-2">
        {[["usuário", COLORS.user], ["service principal", COLORS.sp], ["persona", COLORS.persona], ["IdP", COLORS.idp_persona],
          ["clearance", COLORS.clearance], ["legado", COLORS.legacy], ["objeto", COLORS.securable], ["objeto sensível", "#F2A900"]]
          .map(([l, c]) => <span key={l} className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: c }} />{l}</span>)}
      </div>
      <div className="text-[11px] text-text-dim mt-1">
        <b>Duplo clique</b> num nó com borda tracejada expande (grupo → membros · usuário → grupos · objeto → conteúdo e quem tem GRANT);
        duplo clique de novo recolhe · arraste nós ou o fundo · roda do mouse = zoom · passe o mouse para ver os privilégios
      </div>
    </div>
  );
}
