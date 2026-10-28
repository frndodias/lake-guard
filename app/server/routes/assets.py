"""Gateway de criação governada — por linguagem natural (ai-dev-kit).

Fluxo: usuário descreve o que quer criar -> LLM do Unity interpreta e monta o
spec estruturado -> checamos a permissão efetiva -> se autorizado, criamos VIA
OBO (o asset nasce com o dono correto) e registramos em gateway_events (para o
motor de detecção não gerar falso-positivo sobre o que a app criou).
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server import db
from server.auth import current_user
from server.config import LLM_ENDPOINT, get_app_workspace_id, get_workspace_client
from server.services import effective_permissions, user_groups

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# Criadores por capacidade (via OBO). Cada um recebe (w, name, spec).
# --------------------------------------------------------------------------- #
def _create_job(w, name, spec):
    from databricks.sdk.service.jobs import NotebookTask, Task

    notebook_path = spec.get("notebook_path")
    if not notebook_path:
        raise ValueError("notebook_path é obrigatório")
    task = Task(task_key="main", notebook_task=NotebookTask(notebook_path=notebook_path))
    r = w.jobs.create(name=name, tasks=[task])
    return str(r.job_id), name


def _create_notebook(w, name, spec):
    from databricks.sdk.service.workspace import ImportFormat, Language

    path = spec.get("path") or f"/Shared/{name}"
    parent = path.rsplit("/", 1)[0]
    if parent:
        w.workspace.mkdirs(path=parent)
    w.workspace.import_(
        path=path, format=ImportFormat.SOURCE, language=Language.PYTHON,
        content=base64.b64encode(f"# {name}\n".encode()).decode(), overwrite=False,
    )
    return path, name


def _create_dashboard(w, name, spec):  # noqa: ARG001
    from databricks.sdk.service.dashboards import Dashboard

    d = w.lakeview.create(
        dashboard=Dashboard(
            display_name=name,
            serialized_dashboard='{"pages":[{"name":"main","displayName":"Página"}]}',
        )
    )
    return d.dashboard_id, name


def _create_warehouse(w, name, spec):
    r = w.warehouses.create(
        name=name, cluster_size=spec.get("cluster_size", "2X-Small"),
        max_num_clusters=1, enable_serverless_compute=True,
    )
    return getattr(r, "id", None), name


def _create_cluster(w, name, spec):
    sv = spec.get("spark_version") or w.clusters.select_spark_version(long_term_support=True)
    nt = spec.get("node_type_id") or w.clusters.select_node_type(local_disk=True)
    r = w.clusters.create(
        cluster_name=name, spark_version=sv, node_type_id=nt,
        num_workers=int(spec.get("num_workers", 1)), autotermination_minutes=30,
    )
    return getattr(r, "cluster_id", None), name


def _create_lakebase(w, name, spec):
    from databricks.sdk.service.database import DatabaseInstance

    r = w.database.create_database_instance(
        DatabaseInstance(name=name, capacity=spec.get("capacity", "CU_1"))
    )
    return getattr(r, "name", name), name


def _create_vector_search(w, name, spec):  # noqa: ARG001
    from databricks.sdk.service.vectorsearch import EndpointType

    w.vector_search_endpoints.create_endpoint(name=name, endpoint_type=EndpointType.STANDARD)
    return name, name


# capacidade -> (criador, schema de spec para o LLM)
_CREATORS = {
    "job":           (_create_job,           {"notebook_path": "caminho do notebook (obrigatório), ex: /Workspace/Users/.../nb"}),
    "notebook":      (_create_notebook,      {"path": "caminho opcional; default /Users/<você>/<nome>"}),
    "dashboard":     (_create_dashboard,     {}),
    "warehouse":     (_create_warehouse,     {"cluster_size": "opcional, ex: 2X-Small, Small, Medium"}),
    "cluster":       (_create_cluster,       {"num_workers": "opcional, int (default 1)"}),
    "lakebase":      (_create_lakebase,      {"capacity": "opcional, ex: CU_1, CU_2"}),
    "vector_search": (_create_vector_search, {}),
}
_REQUIRED = {"job": ["notebook_path"]}


class CreateAssetIn(BaseModel):
    capability: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    spec: dict = Field(default_factory=dict)


class NLRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


@router.get("/assets/allowed")
async def allowed_for_me(request: Request):
    """O que o usuário logado pode criar pelo gateway (permitido + suportado)."""
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    groups = user_groups(u.email)
    perms = effective_permissions(u.email, groups, get_app_workspace_id())
    for p in perms.values():
        p["supported"] = p["capability"] in _CREATORS
    return {"email": u.email, "groups": groups, "permissions": list(perms.values())}


def _llm_plan(prompt: str, allowed_supported: list[dict]) -> dict:
    """Chama o LLM para converter a descrição em {capability, name, spec, missing}."""
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    catalog = "\n".join(
        f"- {c['capability']}: {c['label']}. Campos do spec: "
        f"{json.dumps(_CREATORS[c['capability']][1], ensure_ascii=False)}"
        for c in allowed_supported
    )
    system = (
        "Você converte um pedido em linguagem natural para criar um asset no Databricks "
        "em um JSON estruturado. Só pode escolher entre as capacidades abaixo (que o usuário "
        "TEM permissão e o sistema suporta criar):\n"
        f"{catalog}\n\n"
        "Responda SOMENTE com JSON válido, sem markdown, no formato:\n"
        '{\"capability\": \"<code>\", \"name\": \"<nome do asset>\", \"spec\": {<campos>}, '
        '\"missing\": [<campos obrigatórios que faltaram>], \"message\": \"<curto, se não der para decidir>\"}\n'
        "Se o pedido não corresponder a nenhuma capacidade permitida, use capability vazio e explique em message. "
        "Infira um nome sensato se o usuário não der um."
    )
    w = get_workspace_client()
    resp = w.serving_endpoints.query(
        name=LLM_ENDPOINT,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
            ChatMessage(role=ChatMessageRole.USER, content=prompt),
        ],
        max_tokens=500,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return {"capability": "", "message": text[:300]}


@router.post("/assets/nl")
async def create_from_nl(body: NLRequest, request: Request):
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")

    groups = user_groups(u.email)
    perms = effective_permissions(u.email, groups, get_app_workspace_id())
    allowed_supported = [
        {"capability": c, "label": p["label"]}
        for c, p in perms.items() if p["allowed"] and c in _CREATORS
    ]
    if not allowed_supported:
        return {"status": "no_capability", "message": "Você não tem permissão de criação em nenhum tipo suportado."}

    plan = _llm_plan(body.prompt, allowed_supported)
    cap = (plan.get("capability") or "").strip()

    if not cap:
        return {"status": "unclear", "message": plan.get("message") or "Não entendi o que criar.", "plan": plan}
    if cap not in perms or not perms[cap]["allowed"]:
        return {"status": "denied", "capability": cap, "label": perms.get(cap, {}).get("label", cap), "plan": plan}
    if cap not in _CREATORS:
        return {"status": "unsupported", "capability": cap, "plan": plan}

    spec = plan.get("spec") or {}
    missing = [f for f in _REQUIRED.get(cap, []) if not spec.get(f)] or plan.get("missing") or []
    if missing:
        return {"status": "need_info", "capability": cap, "name": plan.get("name"), "missing": missing, "plan": plan}

    # Cria via service principal da app (broker governado). A permissão do
    # usuário já foi validada acima; o SP é o executor sancionado.
    name = plan.get("name") or f"lakeguard-{cap}"
    try:
        asset_id, asset_name = _CREATORS[cap][0](get_workspace_client(), name, spec)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "capability": cap, "message": str(e), "plan": plan}

    db.execute(
        """
        INSERT INTO gateway_events (principal, capability, asset_type, asset_id, asset_name, detail)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (u.email, cap, cap, asset_id, asset_name, json.dumps(spec)),
    )
    return {"status": "created", "capability": cap, "name": asset_name, "asset_id": asset_id, "plan": plan}


@router.post("/assets")
async def create_asset(body: CreateAssetIn, request: Request):
    """Criação direta por capability+spec (usado internamente / testes)."""
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    groups = user_groups(u.email)
    if not effective_permissions(u.email, groups, get_app_workspace_id()).get(body.capability, {}).get("allowed"):
        raise HTTPException(status_code=403, detail=f"Sem permissão para criar '{body.capability}'.")
    if body.capability not in _CREATORS:
        raise HTTPException(status_code=501, detail=f"Criação de '{body.capability}' não suportada.")
    try:
        asset_id, asset_name = _CREATORS[body.capability][0](get_workspace_client(), body.name, body.spec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Falha ao criar asset: {e}") from e
    db.execute(
        "INSERT INTO gateway_events (principal, capability, asset_type, asset_id, asset_name, detail) VALUES (%s,%s,%s,%s,%s,%s)",
        (u.email, body.capability, body.capability, asset_id, asset_name, json.dumps(body.spec)),
    )
    return {"ok": True, "capability": body.capability, "asset_id": asset_id, "name": asset_name}
