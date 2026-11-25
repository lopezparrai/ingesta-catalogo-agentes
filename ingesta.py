"""M6 — Corrida completa por la Batch API (y semana 6: todos los proveedores con un comando).

Nadie espera el alta en tiempo real, así que el trabajo del escritor va por la Batch API: ~50 % menos y
los pedidos de todos los proveedores viajan juntos. Pero un agente con tools no es un pedido único: cada
vuelta del loop necesita el resultado de las tools. Se resuelve por RONDAS:

  ronda 1: un pedido por conversación (lote de 10 productos) en un mismo batch
  -> llega el resultado; las tools (validar GTIN, catálogo, conversión) y los hooks corren acá, en local
  ronda 2: se mandan los tool_result de las conversaciones que siguen activas, en otro batch
  ... hasta que todas terminan. Cada ronda empareja resultados con su conversación por `custom_id`
  (nunca por posición: los resultados vuelven en cualquier orden) y lee el estado de cada resultado
  (un batch "terminado" puede traer errored, expired o canceled mezclados con los exitosos).

Etapas:
  1. Extractores en paralelo (tiempo real, son cortos): un agente por archivo, como en M4.
  2. Consolidación por código (código, sin agente).
  3. Escritor por rondas: `--modo batch` (default) o `--modo tiempo-real` (concurrencia acotada, para
     cuando el deadline es hoy: mismas rondas, pedidos en paralelo con un tope; no es 50 % más barato).

Salidas en resultados/final/: fichas por proveedor, trazas, `cola_de_revision.json` y `resumen_corrida.json`.

Uso:
  py ingesta.py P09_Natural_Vida                          # un proveedor, por Batch API
  py ingesta.py P01_Laboratorio_Andes P08_Importadora_Norte --modo tiempo-real
  py ingesta.py --todos                                   # los proveedores de proveedores.csv, menos el apartado
  py ingesta.py P05_Dermalab                              # el apartado: una sola vez, con el sistema como está
"""
import argparse
import asyncio
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from mcp import ClientSession
from mcp.client.stdio import stdio_client

import agente_base as A
import orquestador as O

SALIDAS = A.RAIZ / "resultados" / "final"
APARTADO = "P05_Dermalab"       # el proveedor que se abre una sola vez (semana 5)
DESCUENTO_BATCH = 0.5           # la Batch API cobra ~50 % menos
MAX_ITERACIONES = 20            # vueltas por conversación, como en run_agent
MAX_ERRORES_API = 2             # reintentos de un pedido que falló por un error transitorio
MAX_RONDAS = 40


@dataclass
class Conv:
    """Una conversación del escritor: un lote de productos de un proveedor."""
    cid: str
    carpeta: str
    esperados: list[str]
    mensajes: list
    fichas: dict = field(default_factory=dict)
    iteraciones: int = 0
    errores_api: int = 0
    reintentos_al_terminar: int = 0
    reintentos_precio: int = 0
    con_precio: set = field(default_factory=set)    # productos cuya extracción trae un precio
    frenos: list = field(default_factory=list)      # lo que frenaron los hooks, con su motivo
    traza: list = field(default_factory=list)
    uso: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_escrito": 0, "cache_leido": 0})
    costo_usd: float = 0.0
    estado: str = "activa"                          # activa | terminada | fallida
    nota: str = ""


import re as _re

_CLAVE_PRECIO = _re.compile(r"(precio|costo|cost|price)", _re.I)


def tiene_precio(producto: dict) -> bool:
    """¿Alguna observación del producto trae un precio? (columna con 'precio' o 'costo' en el nombre y un valor)."""
    for o in producto.get("observaciones", []):
        for k, v in (o.get("campos") or {}).items():
            if _CLAVE_PRECIO.search(str(k)) and str(v).strip() not in ("", "None", "null"):
                return True
    return False


def hook_no_perder_precio(fichas: dict, con_precio: set) -> list[str]:
    """Al terminar: si la extracción trae precio y la ficha quedó sin precio_costo, es un dato perdido en el
    traspaso (ya pasó: un lote entero del escritor lo dejó vacío). Se lo devuelve al modelo para que lo revise."""
    return [i for i, r in fichas.items()
            if i in con_precio and (r.get("ficha") or {}).get("precio_costo") in (None, "")]


# ---------------------------------------------------------------------------
# Rondas: un batch (o concurrencia acotada) por vuelta del loop
# ---------------------------------------------------------------------------

def _a_dict(bloque):
    return bloque if isinstance(bloque, dict) else bloque.model_dump(exclude_none=True)


def mensajes_serializables(mensajes: list) -> list:
    """El historial lleva bloques del SDK (thinking incluido, sin tocar); para el batch viajan como JSON."""
    salida = []
    for m in mensajes:
        c = m["content"]
        salida.append({"role": m["role"], "content": c if isinstance(c, str) else [_a_dict(b) for b in c]})
    return salida


def armar_pedido(conv: Conv, system: list, tools: list) -> dict:
    return {"custom_id": conv.cid, "params": {
        "model": A.MODELO, "max_tokens": 16000, "system": system, "tools": tools,
        "messages": mensajes_serializables(conv.mensajes)}}


def ronda_batch(pedidos: list[dict], espera_max_min: int) -> tuple[dict, dict]:
    """Manda los pedidos como un batch y espera a que termine. Devuelve ({custom_id: (estado, dato)}, info)."""
    lote = A.client.messages.batches.create(requests=pedidos)
    print(f"  [batch {lote.id}] {len(pedidos)} pedido(s) enviados")
    inicio, espera = time.time(), 10.0
    while True:
        lote = A.client.messages.batches.retrieve(lote.id)
        c = lote.request_counts
        print(f"  [batch] {lote.processing_status}: en proceso {c.processing} | ok {c.succeeded} | "
              f"error {c.errored} | vencidos {c.expired} | cancelados {c.canceled}")
        if lote.processing_status == "ended":
            break
        if time.time() - inicio > espera_max_min * 60:
            A.client.messages.batches.cancel(lote.id)
            raise TimeoutError(f"El batch {lote.id} no terminó en {espera_max_min} min; se canceló.")
        time.sleep(espera)
        espera = min(espera * 1.5, 60)

    resultados = {}
    for r in A.client.messages.batches.results(lote.id):   # el join es custom_id, nunca la posición
        if r.result.type == "succeeded":
            resultados[r.custom_id] = ("ok", r.result.message)
        else:
            detalle = str(getattr(r.result, "error", "") or "")[:200]
            resultados[r.custom_id] = ("error", f"{r.result.type} {detalle}".strip())
    c = lote.request_counts
    return resultados, {"batch_id": lote.id, "ok": c.succeeded, "error": c.errored,
                        "vencidos": c.expired, "cancelados": c.canceled}


def ronda_tiempo_real(pedidos: list[dict], concurrencia: int) -> tuple[dict, dict]:
    """Los mismos pedidos, en paralelo con un tope (el tope evita el 429 en cascada)."""
    def uno(p: dict):
        try:
            return p["custom_id"], ("ok", A.client.messages.create(**p["params"]))
        except Exception as e:  # el SDK ya reintentó los transitorios; esto es lo que quedó
            return p["custom_id"], ("error", f"{type(e).__name__}: {e}"[:300])
    with ThreadPoolExecutor(max_workers=concurrencia) as ex:
        resultados = dict(ex.map(uno, pedidos))
    ok = sum(1 for e, _ in resultados.values() if e == "ok")
    return resultados, {"batch_id": None, "ok": ok, "error": len(pedidos) - ok, "vencidos": 0, "cancelados": 0}


# ---------------------------------------------------------------------------
# Lo que hace cada vuelta con la respuesta: tools y hooks, igual que run_agent
# ---------------------------------------------------------------------------

def _sumar_uso(conv: Conv, msg, factor: float) -> None:
    u = msg.usage
    uso = {"input": u.input_tokens, "output": u.output_tokens,
           "cache_escrito": u.cache_creation_input_tokens or 0, "cache_leido": u.cache_read_input_tokens or 0}
    for k, v in uso.items():
        conv.uso[k] += v
    conv.costo_usd += A.costo_usd(uso) * factor


def _fallar(conv: Conv, nota: str) -> None:
    conv.estado, conv.nota = "fallida", nota
    print(f"  [{conv.cid}] FALLÓ: {nota}")


async def avanzar(conv: Conv, msg, session, factor: float) -> None:
    """Aplica la respuesta del modelo a la conversación: ejecuta tools, corre hooks, decide si terminó."""
    _sumar_uso(conv, msg, factor)
    if msg.stop_reason == "refusal":
        return _fallar(conv, f"el modelo se negó ({getattr(msg, 'stop_details', None)})")
    conv.mensajes.append({"role": "assistant", "content": msg.content})
    texto_final = "\n".join(b.text for b in msg.content if b.type == "text")

    if msg.stop_reason == "tool_use":
        conv.iteraciones += 1
        resultados = []
        for b in msg.content:
            if b.type != "tool_use":
                continue
            motivo = A.correr_hooks_antes("escritor", b.name, b.input)
            if motivo:
                texto, es_error = f"Bloqueado por hook: {motivo}", True
                if b.name == "registrar_ficha":
                    conv.frenos.append({"item_id": b.input.get("item_id"), "hook": motivo})
                    print(f"  [hook FRENÓ] {b.input.get('item_id')}: {motivo[:160]}")
            elif b.name == "registrar_ficha":
                texto, es_error = A.registrar(conv.fichas, b.input)
            else:
                try:
                    r = await session.call_tool(b.name, b.input)
                    texto = A._texto_de(r)
                    es_error = bool(getattr(r, "is_error", None) or getattr(r, "isError", False))
                except Exception as e:  # el error vuelve al modelo, no tumba la corrida
                    texto, es_error = f"Error ejecutando la tool: {e}", True
            A.hook_despues_traza(conv.traza, b.name, b.input, texto, es_error)
            resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": texto, "is_error": es_error})
        conv.mensajes.append({"role": "user", "content": resultados})
        if conv.iteraciones >= MAX_ITERACIONES:
            _fallar(conv, f"llegó al límite de {MAX_ITERACIONES} iteraciones")
        return

    if msg.stop_reason != "end_turn":
        return _fallar(conv, f"stop_reason inesperado: {msg.stop_reason}")

    faltan = [i for i in conv.esperados if i not in conv.fichas]
    if faltan:   # el código, no el prompt, decide cuándo está completa la tarea
        conv.mensajes.append({"role": "user", "content": (
            f"Todavía no registraste estos productos: {', '.join(faltan)}. "
            "Registralos con registrar_ficha antes de terminar.")})
        conv.iteraciones += 1
        if conv.iteraciones >= MAX_ITERACIONES:
            _fallar(conv, f"llegó al límite de {MAX_ITERACIONES} iteraciones sin registrar {faltan}")
        return

    perdidos = hook_no_perder_precio(conv.fichas, conv.con_precio)
    if perdidos and conv.reintentos_precio < A.HOOKS_REINTENTOS_AL_TERMINAR:
        conv.reintentos_precio += 1
        conv.frenos.append({"item_id": None, "hook": f"[hook_no_perder_precio] sin precio_costo aunque la extracción lo trae: {', '.join(perdidos)}"})
        conv.mensajes.append({"role": "user", "content": (
            f"Bloqueado por hook al terminar: estos productos tienen precio en los datos extraídos y quedaron con "
            f"precio_costo vacío: {', '.join(perdidos)}. Registralos de nuevo con el precio (convertido a número) y "
            "su fuente. Si el precio quedó vacío a propósito por una regla del criterio, dejalo y explicalo en los motivos.")})
        return
    problemas = A.hook_al_terminar_fuentes(conv.fichas)   # hook al terminar: ningún campo sin fuente
    if problemas and conv.reintentos_al_terminar < A.HOOKS_REINTENTOS_AL_TERMINAR:
        conv.reintentos_al_terminar += 1
        detalle = "; ".join(f"{i}: {c}" for i, c in problemas)
        conv.frenos.append({"item_id": None, "hook": f"[hook_al_terminar_fuentes] campos sin fuente: {detalle}"})
        conv.mensajes.append({"role": "user", "content": (
            f"Bloqueado por hook al terminar: hay campos completados sin fuente ({detalle}). Registrá de nuevo "
            "esas fichas con la fuente de cada campo, o con el campo en null si no tiene fuente.")})
        return
    if problemas:
        A.vaciar_campos_sin_fuente(conv.fichas, problemas)
    conv.estado, conv.nota = "terminada", texto_final[:200]


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------

async def escribir_por_rondas(convs: list[Conv], modo: str, concurrencia: int, espera_max_min: int) -> list[dict]:
    rondas = []
    async with stdio_client(A.SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prompt = await session.get_prompt("criterio_revision")     # el criterio viene del servidor MCP
            criterio = "\n".join(m.content.text for m in prompt.messages if getattr(m.content, "text", None))
            system = A.armar_system(criterio, O.SYSTEM_ESCRITOR_EXTRA)
            tools_mcp = await session.list_tools()
            tools = [{"name": t.name, "description": t.description or "",
                      "input_schema": getattr(t, "input_schema", None) or t.inputSchema}
                     for t in tools_mcp.tools] + [A.REGISTRAR_FICHA]
            tools = [t for t in tools if t["name"] in A.PERMISOS["escritor"]]   # permisos del escritor, en código

            for n in range(1, MAX_RONDAS + 1):
                activas = [c for c in convs if c.estado == "activa"]
                if not activas:
                    break
                inicio = time.perf_counter()
                print(f"\n--- Ronda {n}: {len(activas)} conversación(es) activa(s), modo {modo} ---")
                pedidos = [armar_pedido(c, system, tools) for c in activas]
                if modo == "batch":
                    resultados, info = ronda_batch(pedidos, espera_max_min)
                else:
                    resultados, info = ronda_tiempo_real(pedidos, concurrencia)
                factor = DESCUENTO_BATCH if modo == "batch" else 1.0

                for c in activas:
                    estado, dato = resultados.get(c.cid, ("error", "sin resultado en el batch"))
                    if estado == "ok":
                        await avanzar(c, dato, session, factor)
                        continue
                    c.errores_api += 1     # error transitorio: se reencola; uno de payload (400) no se reintenta
                    if "invalid_request" in dato or "BadRequest" in dato or c.errores_api > MAX_ERRORES_API:
                        _fallar(c, f"error de la API: {dato}")
                    else:
                        print(f"  [{c.cid}] {dato}: se reencola en la próxima ronda")
                rondas.append({"ronda": n, "pedidos": len(pedidos), "segundos": round(time.perf_counter() - inicio, 1),
                               **info})
            for c in convs:
                if c.estado == "activa":
                    _fallar(c, f"se agotaron las {MAX_RONDAS} rondas")
    return rondas


def carpetas_todos() -> list[str]:
    with open(A.RAIZ / "data" / "proveedores" / "proveedores.csv", encoding="utf-8-sig", newline="") as f:
        return [fila["carpeta"].strip() for fila in csv.DictReader(f) if fila["carpeta"].strip() != APARTADO]


def main() -> None:
    ap = argparse.ArgumentParser(description="Corrida completa por Batch API (M6)")
    ap.add_argument("carpetas", nargs="*", help="carpetas de proveedor, ej. P09_Natural_Vida")
    ap.add_argument("--todos", action="store_true", help=f"todos los de proveedores.csv, menos {APARTADO}")
    ap.add_argument("--modo", choices=["batch", "tiempo-real"], default="batch")
    ap.add_argument("--concurrencia", type=int, default=8, help="pedidos en vuelo en modo tiempo-real")
    ap.add_argument("--workers", type=int, default=8, help="extractores simultáneos")
    ap.add_argument("--codigos", default="", help="solo estos códigos, separados por coma")
    ap.add_argument("--espera-max", type=int, default=120, help="minutos máximos de espera por ronda de batch")
    a = ap.parse_args()
    carpetas = carpetas_todos() if a.todos else a.carpetas
    if not carpetas:
        ap.error("indicá carpetas o --todos")
    codigos = [c.strip() for c in a.codigos.split(",") if c.strip()] or None
    for c in carpetas:
        if not (O.PROVEEDORES / c).is_dir():
            ap.error(f"no existe la carpeta {c!r}")

    inicio = time.perf_counter()
    print(f"Proveedores: {', '.join(carpetas)} | modo {a.modo}")

    # 1. Extractores en paralelo (tiempo real): cada tarea es un archivo, o una parte de un CSV largo
    t = time.perf_counter()
    tareas = [(c, u) for c in carpetas for u in O.unidades_de_extraccion(c)]
    print(f"\n=== Extracción: {len(tareas)} tarea(s) en paralelo (máx. {a.workers}) ===")
    with ThreadPoolExecutor(max_workers=min(a.workers, len(tareas))) as ex:
        extracciones = list(ex.map(lambda cu: O.extraer(cu[1]), tareas))
    t_extraccion = round(time.perf_counter() - t, 1)
    por_carpeta = {c: [] for c in carpetas}
    for (c, _), e in zip(tareas, extracciones):
        por_carpeta[c].append(e)

    # 2. Consolidación por código + conversaciones del escritor
    convs, productos_de, costo_extraccion = [], {}, {}
    for c in carpetas:
        pid = A.proveedor_id_de(c)
        productos, fds, avisos, contextos = O.consolidar(pid, por_carpeta[c], codigos)
        productos_de[c] = productos
        costo_extraccion[c] = sum(e["costo_usd"] for e in por_carpeta[c])
        for a_ in avisos:
            print(f"  [aviso {c}] {a_}")
        codigos_c = list(productos)
        for i in range(0, len(codigos_c), O.LOTE_ESCRITOR):
            lote = codigos_c[i:i + O.LOTE_ESCRITOR]
            convs.append(Conv(
                cid=f"{pid}-lote{i // O.LOTE_ESCRITOR}", carpeta=c,
                esperados=[productos[x]["item_id"] for x in lote],
                con_precio={productos[x]["item_id"] for x in lote if tiene_precio(productos[x])},
                mensajes=[{"role": "user", "content": O.tarea_escritor(pid, productos, lote, contextos, fds)}]))
        print(f"  [consolidación {c}] {len(productos)} producto(s), {len(fds)} FDS, "
              f"{len([x for x in convs if x.carpeta == c])} lote(s)")

    # 3. Escritor por rondas (Batch API o concurrencia acotada)
    t = time.perf_counter()
    rondas = asyncio.run(escribir_por_rondas(convs, a.modo, a.concurrencia, a.espera_max))
    t_escritura = round(time.perf_counter() - t, 1)
    total = round(time.perf_counter() - inicio, 1)

    # 4. Salidas: fichas, cola de revisión, qué falló y cuánto costó cada ficha
    SALIDAS.mkdir(parents=True, exist_ok=True)
    cola, resumen_prov = [], []
    print("\n================ RESUMEN ================")
    for c in carpetas:
        cs = [x for x in convs if x.carpeta == c]
        fichas = {}
        for x in cs:
            fichas.update(x.fichas)
        esperados = [productos_de[c][k]["item_id"] for k in productos_de[c]]
        faltan = [i for i in esperados if i not in fichas]
        costo = costo_extraccion[c] + sum(x.costo_usd for x in cs)
        fallas = [{"lote": x.cid, "motivo": x.nota} for x in cs if x.estado == "fallida"]
        frenos = [f for x in cs for f in x.frenos]
        (SALIDAS / f"{c}_extraccion.json").write_text(
            json.dumps(por_carpeta[c], indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        (SALIDAS / f"{c}.json").write_text(
            json.dumps(list(fichas.values()), indent=2, ensure_ascii=False), encoding="utf-8")
        (SALIDAS / f"{c}_traza.json").write_text(json.dumps({
            "modo": a.modo, "fichas": len(fichas), "sin_registrar": faltan, "fallas": fallas,
            "frenos_de_hooks": frenos, "costo_usd": round(costo, 4),
            "costo_por_ficha_usd": round(costo / len(fichas), 5) if fichas else None,
            "uso_escritor": {k: sum(x.uso[k] for x in cs) for k in ("input", "output", "cache_escrito", "cache_leido")},
            "lotes": [{"lote": x.cid, "estado": x.estado, "iteraciones": x.iteraciones,
                       "costo_usd": round(x.costo_usd, 4)} for x in cs],
        }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        for r in fichas.values():
            if r["estado"] == "a_revision":
                cola.append({"item_id": r["item_id"], "motivos_revision": r["motivos_revision"],
                             "duplicado_de": r["duplicado_de"]})
        estados = {e: sum(1 for r in fichas.values() if r["estado"] == e)
                   for e in ("lista_para_alta", "duplicado", "a_revision")}
        print(f"{c}: {len(fichas)}/{len(esperados)} fichas {estados} | frenos de hooks: {len(frenos)} | "
              f"USD {costo:.4f}" + (f" ({costo / len(fichas):.5f} por ficha)" if fichas else ""))
        if faltan:
            print(f"   sin registrar: {faltan}")
        for f in fallas:
            print(f"   falló {f['lote']}: {f['motivo']}")
        O.comparar_con_m3({"carpeta": c, "fichas": fichas})
        resumen_prov.append({"carpeta": c, "fichas": len(fichas), "esperadas": len(esperados), "estados": estados,
                             "costo_usd": round(costo, 4), "frenos_de_hooks": len(frenos), "fallas": fallas})

    costo_total = round(sum(p["costo_usd"] for p in resumen_prov), 4)
    n_fichas = sum(p["fichas"] for p in resumen_prov)
    (SALIDAS / "cola_de_revision.json").write_text(json.dumps(cola, indent=2, ensure_ascii=False), encoding="utf-8")
    (SALIDAS / "resumen_corrida.json").write_text(json.dumps({
        "modo": a.modo, "segundos_total": total, "segundos_extraccion": t_extraccion,
        "segundos_escritura": t_escritura, "rondas": rondas, "fichas": n_fichas, "costo_usd": costo_total,
        "costo_por_ficha_usd": round(costo_total / n_fichas, 5) if n_fichas else None,
        "proveedores": resumen_prov}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nTiempo total: {total} s (extracción {t_extraccion} s, escritura {t_escritura} s en {len(rondas)} ronda(s))")
    print(f"Costo total: USD {costo_total} | fichas: {n_fichas}"
          + (f" | por ficha: USD {costo_total / n_fichas:.5f}" if n_fichas else ""))
    print(f"Cola de revisión: {len(cola)} producto(s) en resultados/final/cola_de_revision.json")
    print("(El costo no incluye las lecturas de PDF que hace el servidor con su propio llamado a la API.)")


if __name__ == "__main__":
    main()
