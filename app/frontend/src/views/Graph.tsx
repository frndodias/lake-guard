import { useEffect, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape";
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

type Layout = "rings" | "force";

function layoutOptions(kind: Layout): LayoutOptions {
  if (kind === "force") {
    return {
      name: "cose", animate: true, animationDuration: 500, fit: true, padding: 40,
      idealEdgeLength: () => 120, nodeRepulsion: () => 12000, gravity: 0.25,
    } as LayoutOptions;
  }
  return {
    name: "concentric", animate: true, animationDuration: 400, fit: true, padding: 40,
    concentric: (n: cytoscape.NodeSingular) => n.data("level"), levelWidth: () => 1,
    minNodeSpacing: 46, spacingFactor: 1.05, startAngle: (3 / 2) * Math.PI,
  } as LayoutOptions;
}

/** Rede de acessos interativa: arraste nós, arraste o fundo para mover, roda do mouse para zoom. */
export function GraphView({ data, height = 560 }: { data: GraphData; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [layout, setLayout] = useState<Layout>("rings");
  const [selected, setSelected] = useState<{ id: string; label: string; kind: string; full: string } | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const text = themeColor("--text", "#1B3139");
    const dim = themeColor("--text-dim", "#5B6B70");
    const surface = themeColor("--surface", "#FFFFFF");
    const maxRing = Math.max(1, ...data.nodes.map((n) => n.ring));
    const elements: ElementDefinition[] = [
      ...data.nodes.map((n) => ({
        data: { id: n.id, label: n.label, color: color(n), kind: n.kind, level: maxRing - n.ring + 1,
          center: n.ring === 0, full: n.full_name || "" },
        classes: [n.kind, n.ring === 0 ? "center" : ""].join(" "),
      })),
      ...data.edges.map((e, i) => ({
        data: { id: `e${i}`, source: e.from, target: e.to, label: (e.privileges || []).join(", ").replace(/_/g, " ") },
        classes: e.kind,
      })),
    ];
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
        { selector: "node.center", style: { width: 34, height: 34, "font-size": 12, "font-weight": "bold", "border-color": text } },
        { selector: "node.securable", style: { shape: "round-rectangle", width: 16, height: 16 } },
        { selector: "node:selected", style: { "border-color": "#FF3621", "border-width": 3 } },
        { selector: "edge", style: {
          width: 1.5, "line-color": dim, "target-arrow-color": dim, "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.8, opacity: 0.65,
        } },
        { selector: "edge.member", style: { "line-style": "dashed" } },
        { selector: "edge.grant", style: { "line-color": "#FF3621", "target-arrow-color": "#FF3621", width: 2 } },
        { selector: "edge.show-label", style: {
          label: "data(label)", "font-size": 9, color: text, "text-background-color": surface,
          "text-background-opacity": 0.92, "text-background-padding": "2px", "text-rotation": "autorotate", opacity: 1,
        } },
        { selector: ".faded", style: { opacity: 0.1 } },
      ],
      layout: layoutOptions("rings"),
    });
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
      setSelected({ id: d.id, label: d.label, kind: d.kind, full: d.full });
    });
    cy.on("tap", (ev) => { if (ev.target === cy) setSelected(null); });
    cy.on("dbltap", "node", (ev) => {
      const d = ev.target.data();
      if (d.kind === "securable") go("explore", "asset", d.full);
      else if (!d.center) go("explore", "identity", d.id);
    });
    cyRef.current = cy;
    setLayout("rings");
    return () => { cy.destroy(); cyRef.current = null; };
  }, [data]);

  const relayout = (kind: Layout) => {
    setLayout(kind);
    cyRef.current?.layout(layoutOptions(kind)).run();
  };
  const exportPng = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const a = document.createElement("a");
    a.href = cy.png({ full: true, scale: 2, bg: themeColor("--surface", "#FFFFFF") });
    a.download = "rede-de-acessos.png";
    a.click();
  };
  const open = () => {
    if (!selected) return;
    if (selected.kind === "securable") go("explore", "asset", selected.full);
    else go("explore", "identity", selected.id);
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
        <button className="btn-ghost !py-1.5 text-xs" onClick={() => cyRef.current?.fit(undefined, 40)}>Centralizar</button>
        <button className="btn-ghost !py-1.5 text-xs" onClick={() => relayout(layout)}>Reorganizar</button>
        <button className="btn-ghost !py-1.5 text-xs" onClick={exportPng}>Exportar PNG</button>
        {selected && (
          <span className="text-xs text-text-dim ml-auto flex items-center gap-2">
            <b className="text-text">{selected.label}</b>
            <button className="text-lava hover:underline" onClick={open}>abrir →</button>
          </span>
        )}
      </div>
      <div ref={ref} className="w-full rounded-lg border border-border bg-bg/40" style={{ height }} />
      <div className="flex flex-wrap gap-3 text-[11px] text-text-dim mt-2">
        {[["usuário", COLORS.user], ["service principal", COLORS.sp], ["persona", COLORS.persona], ["IdP", COLORS.idp_persona],
          ["clearance", COLORS.clearance], ["legado", COLORS.legacy], ["objeto", COLORS.securable], ["objeto sensível", "#F2A900"]]
          .map(([l, c]) => <span key={l} className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: c }} />{l}</span>)}
        <span>· arraste nós ou o fundo · roda do mouse = zoom · clique seleciona · duplo clique abre · passe o mouse para ver os privilégios</span>
      </div>
    </div>
  );
}
