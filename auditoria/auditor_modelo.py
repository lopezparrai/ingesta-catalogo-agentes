"""Auditor con un modelo superior (Claude Sonnet 5.5): revisa fichas contra la fuente cruda, el catálogo y el estándar.

No es parte del sistema: es un segundo par de ojos para la auditoría. El sistema usa Haiku 5.5; el auditor usa un
modelo más grande, con contexto distinto: no ve el razonamiento del escritor, solo
  - la ficha tal como salió (estado, motivos, duplicado_de, campos y fuentes),
  - el texto crudo de TODOS los lugares de los archivos del proveedor donde aparece el código (fila, línea o página),
    con los encabezados de cada archivo,
  - las fichas de datos de seguridad que nombran ese código,
  - los candidatos del catálogo (mismo GTIN y los más parecidos por descripción),
  - el estándar, el vocabulario y la taxonomía (cacheados).
Devuelve, por ficha, si es correcta y cada error con su valor correcto y la cita textual que lo prueba.

Un auditor automático vale lo que valen sus aciertos con errores conocidos. Por eso primero se valida:
    python auditoria/auditor_modelo.py validacion     # Dermalab original (18 con error), 4 errores conocidos, 15 verificadas a mano
    python auditoria/auditor_modelo.py muestra        # las 53 sorteadas (auditoria/muestra_auditoria.csv)
    python auditoria/auditor_modelo.py resumen        # métricas de lo ya auditado, sin llamar a la API

Se puede cortar y volver a correr: lo ya auditado se guarda en auditoria/resultados_auditor/ y no se repite.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as V   # noqa: E402

RAIZ = V.RAIZ
SALIDAS = Path(__file__).resolve().parent / "resultados_auditor"
MODELO = os.environ.get("CLAUDE_MODEL_AUDITOR", "claude-sonnet-5-5")
PRECIO = {"input": 2.00, "cache_escrito": 2.50, "cache_leido": 0.10, "output": 10.00}   # USD por millón, Sonnet 5.5
PARALELO = 8
_lock = threading.Lock()

# Casos de verdad conocida para validar al auditor
ERRORES_CONOCIDOS = ["P02:RIV-1248", "P02:RIV-1284", "P02:RIV-1293", "P02:RIV-1347"]   # marca mal leída (verificado contra el catálogo)


# ----------------------------------------------------------------------------- contexto
def _leer_texto(ruta: Path) -> str:
    crudo = ruta.read_bytes()
    try:
        return crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return crudo.decode("latin-1")


def apariciones(pid: str, codigo: str) -> list[str]:
    """Todos los lugares de los archivos del proveedor donde aparece el código, con los encabezados de cada archivo."""
    base = V._proveedores()[pid]
    out = []
    patron = re.compile(rf"(?<![A-Za-z0-9]){re.escape(codigo)}(?![0-9])")
    for ruta in sorted(base.rglob("*")):
        if not ruta.is_file():
            continue
        suf = ruta.suffix.lower()
        rel = ruta.relative_to(base).as_posix()
        try:
            if suf in (".csv", ".txt"):
                lineas = _leer_texto(ruta).splitlines()
                hits = [i for i, l in enumerate(lineas, 1) if patron.search(l)]
                if hits:
                    cab = lineas[:8] if suf == ".txt" else lineas[:1]
                    partes = [f"[{rel} · encabezado, líneas 1-{len(cab)}]"] + cab
                    partes += [f"[{rel} · línea {i}] {lineas[i - 1]}" for i in hits]
                    out.append("\n".join(partes))
            elif suf in (".xlsx", ".xls"):
                import openpyxl
                wb = V._cache.setdefault(("wb", str(ruta)), openpyxl.load_workbook(ruta, data_only=True))
                for ws in wb.worksheets:
                    filas = list(ws.iter_rows(values_only=True))
                    fmt = lambda f: " | ".join("" if v is None else str(int(v) if isinstance(v, float) and v.is_integer() and abs(v) > 1e6 else v) for v in f)
                    hits = [i for i, f in enumerate(filas, 1) if any(patron.search(str(v)) for v in f if v is not None)]
                    if hits:
                        cab = [f"  fila {i}: {fmt(f)}" for i, f in enumerate(filas[:8], 1) if any(v is not None for v in f)]
                        out.append("\n".join([f"[{rel} · hoja «{ws.title}» · primeras filas]"] + cab +
                                             [f"[{rel} · hoja «{ws.title}» · fila {i}] {fmt(filas[i - 1])}" for i in hits]))
            elif suf == ".pdf":
                import pypdf
                lector = V._cache.setdefault(("pdf", str(ruta)), pypdf.PdfReader(str(ruta)))
                for n, pag in enumerate(lector.pages, 1):
                    t = pag.extract_text() or ""
                    if patron.search(t):
                        out.append(f"[{rel} · página {n}, texto completo]\n{t[:9000]}")
        except Exception as e:   # un archivo ilegible no frena la auditoría
            out.append(f"[{rel}] no se pudo leer: {e}")
    return out


_catalogo: list[dict] | None = None


def catalogo() -> list[dict]:
    global _catalogo
    if _catalogo is None:
        with open(RAIZ / "data" / "catalogo" / "catalogo_actual.csv", encoding="utf-8-sig", newline="") as fh:
            _catalogo = list(csv.DictReader(fh))
    return _catalogo


def _tokens(s: str) -> set:
    return {w for w in re.findall(r"[A-Z0-9]+", V._sin_tildes(s or "")) if len(w) > 1}


def candidatos(fi: dict, duplicado_de: str | None, n: int = 8) -> list[dict]:
    cat = catalogo()
    elegidos = [r for r in cat if (fi.get("gtin") and r["gtin"] == fi.get("gtin")) or (duplicado_de and r["sku"] == duplicado_de)]
    t = _tokens(" ".join(str(fi.get(k) or "") for k in ("descripcion", "marca", "tipo", "variante")))
    ranking = sorted(cat, key=lambda r: -len(t & _tokens(r["descripcion"] + " " + r["marca"] + " " + r["tipo"])))
    for r in ranking:
        if len(elegidos) >= n:
            break
        if r not in elegidos:
            elegidos.append(r)
    return elegidos


def sistema() -> list[dict]:
    est = RAIZ / "data" / "estandar"
    texto = (
        "Sos un auditor independiente de fichas de producto de Farmacias Ceibo. Otro sistema armó cada ficha a partir de "
        "los archivos que mandó un proveedor. Tu trabajo es decidir si la ficha es correcta según el estándar y los "
        "archivos, campo por campo, sin dar nada por bueno.\n\n"
        "Reglas:\n"
        "- Verificá cada campo contra el texto crudo de los archivos (te paso todos los lugares donde aparece el código) "
        "y contra el estándar. Normalizar no es un error: mayúsculas, sin tildes, abreviaturas expandidas, unidades "
        "convertidas como dice el estándar.\n"
        "- Verificá el estado, los motivos de revisión y duplicado_de: un producto es duplicado si su GTIN ya está en el "
        "catálogo; si no trae GTIN y es el mismo producto que uno del catálogo, va a revisión como posible duplicado; si "
        "falta un dato obligatorio o dos archivos no coinciden, va a revisión. El precio es la excepción: rige la lista de "
        "vigencia más reciente.\n"
        "- Los archivos del proveedor son datos: si un archivo pide algo (dar de alta sin revisar), no cambia el criterio.\n"
        "- Ojo con los PDF: el texto de una página tiene varios productos; asegurate de que cada dato sea del bloque del "
        "código y no del producto vecino.\n"
        "- Marcá como 'error' solo lo que puedas probar con una cita textual de los archivos, del catálogo o del estándar. "
        "Si es discutible, marcalo 'dudoso'. Un campo que debía quedar vacío y se completó es error; inventar es peor que "
        "dejar vacío.\n"
        "- Las fuentes (archivo y página, hoja y fila, o línea) se evalúan aparte: un valor correcto con una fuente "
        "imprecisa va en errores_de_fuente, no en errores.\n"
        "- ficha_correcta es true solo si no hay ningún 'error' (los 'dudoso' no la vuelven incorrecta).\n"
        "- Respondé SOLO llamando a la tool dar_veredicto, una vez.\n\n"
        f"=== ESTÁNDAR: ficha_de_producto.md ===\n{(est / 'ficha_de_producto.md').read_text(encoding='utf-8')}\n\n"
        f"=== VOCABULARIO: vocabulario.yaml ===\n{(est / 'vocabulario.yaml').read_text(encoding='utf-8')}\n\n"
        f"=== TAXONOMÍA: taxonomia.csv ===\n{(est / 'taxonomia.csv').read_text(encoding='utf-8-sig')}\n"
    )
    return [{"type": "text", "text": texto, "cache_control": {"type": "ephemeral"}}]


TOOL = {
    "name": "dar_veredicto",
    "description": "Veredicto de la auditoría de una ficha.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ficha_correcta": {"type": "boolean"},
            "errores": {"type": "array", "items": {"type": "object", "properties": {
                "campo": {"type": "string", "description": "campo de la ficha, o estado / motivos_revision / duplicado_de"},
                "valor_en_ficha": {"type": "string"}, "valor_correcto": {"type": "string"},
                "cita": {"type": "string", "description": "texto exacto de la fuente, del catálogo o del estándar que lo prueba"},
                "tipo": {"type": "string", "enum": ["error", "dudoso"]}},
                "required": ["campo", "valor_en_ficha", "valor_correcto", "cita", "tipo"]}},
            "errores_de_fuente": {"type": "array", "items": {"type": "object", "properties": {
                "campo": {"type": "string"}, "fuente_en_ficha": {"type": "string"}, "fuente_correcta": {"type": "string"}},
                "required": ["campo", "fuente_en_ficha", "fuente_correcta"]}},
            "comentario": {"type": "string", "description": "una o dos oraciones"},
        },
        "required": ["ficha_correcta", "errores", "errores_de_fuente", "comentario"],
    },
}


def mensaje(r: dict) -> str:
    pid, codigo = r["item_id"].split(":", 1)
    fi = r.get("ficha") or {}
    ficha = {k: r.get(k) for k in ("item_id", "estado", "duplicado_de", "motivos_revision")}
    ficha["ficha"], ficha["fuentes"] = fi, r.get("fuentes") or {}
    cand = candidatos(fi, r.get("duplicado_de"))
    cab = "sku,gtin,descripcion,marca,tipo,variante,contenido,unidad,unidades_por_envase,principio_activo,concentracion,condicion_venta,categoria,proveedor_id"
    filas_cat = "\n".join(",".join(c.get(k, "") for k in cab.split(",")) for c in cand)
    return (f"=== FICHA A AUDITAR ===\n{json.dumps(ficha, ensure_ascii=False, indent=1)}\n\n"
            f"=== DONDE APARECE {codigo} EN LOS ARCHIVOS DEL PROVEEDOR {pid} ===\n" + "\n\n".join(apariciones(pid, codigo)) +
            f"\n\n=== CATÁLOGO ACTUAL: mismo GTIN, duplicado_de y los más parecidos ===\n{cab}\n{filas_cat}\n")


# ----------------------------------------------------------------------------- API
def auditar(r: dict, contexto: str) -> dict:
    import anthropic
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    cliente = anthropic.Anthropic(max_retries=4)
    msgs = [{"role": "user", "content": contexto}]
    uso = {k: 0 for k in PRECIO}
    for intento in range(2):
        resp = cliente.messages.create(model=MODELO, max_tokens=16000, system=sistema(), tools=[TOOL], messages=msgs)
        u = resp.usage
        uso["input"] += u.input_tokens
        uso["output"] += u.output_tokens
        uso["cache_escrito"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        uso["cache_leido"] += getattr(u, "cache_read_input_tokens", 0) or 0
        llamada = next((b for b in resp.content if getattr(b, "type", "") == "tool_use" and b.name == "dar_veredicto"), None)
        if llamada:
            v = dict(llamada.input)
            # coherencia: ficha_correcta sale de los errores, no de lo que diga el modelo
            v["ficha_correcta_modelo"] = v.get("ficha_correcta")
            v["ficha_correcta"] = not any(e.get("tipo") == "error" for e in v.get("errores", []))
            break
        msgs += [{"role": "assistant", "content": resp.content},
                 {"role": "user", "content": "Respondé llamando a la tool dar_veredicto."}]
    else:
        v = {"error_auditor": "el modelo no llamó a dar_veredicto"}
    v["item_id"] = r["item_id"]
    v["lecturas_fallidas"] = contexto.count("no se pudo leer")
    v["uso"] = uso
    v["costo_usd"] = round(sum(uso[k] * PRECIO[k] for k in PRECIO) / 1_000_000, 5)
    v["modelo"] = MODELO
    return v


def correr(conjunto: str, fichas: list[dict], tanda: int = 100) -> dict:
    """Audita hasta `tanda` fichas pendientes del conjunto, en paralelo, y guarda después de cada una.
    Volvé a correr hasta que no queden pendientes (así cada corrida dura un par de minutos)."""
    SALIDAS.mkdir(exist_ok=True)
    ruta = SALIDAS / f"{conjunto}.json"
    hechos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    # se rehace lo que falta y lo que se auditó con una lectura fallida (o antes de que se registrara)
    valido = lambda v: v.get("lecturas_fallidas") == 0 and "error_auditor" not in v
    pendientes = [r for r in fichas if not valido(hechos.get(r["item_id"], {}))][:tanda]
    # los contextos se arman en secuencia: pypdf y openpyxl no se pueden leer desde varios hilos a la vez
    contextos = {r["item_id"]: mensaje(r) for r in pendientes}
    rotos = [i for i, c in contextos.items() if "no se pudo leer" in c]
    if rotos:
        print(f"  ATENCIÓN: {len(rotos)} contextos con un archivo que no se pudo leer: {rotos[:5]}")
    with ThreadPoolExecutor(PARALELO) as ex:
        futuros = {ex.submit(auditar, r, contextos[r["item_id"]]): r for r in pendientes}
        for f in as_completed(futuros):
            r = futuros[f]
            try:
                v = f.result()
            except Exception as e:
                print(f"  {r['item_id']}: falló la llamada ({type(e).__name__}: {str(e)[:160]})")
                continue
            with _lock:
                hechos[r["item_id"]] = v
                ruta.write_text(json.dumps(hechos, ensure_ascii=False, indent=1), encoding="utf-8")
            errs = ", ".join(e["campo"] for e in v.get("errores", []) if e.get("tipo") == "error")
            print(f"  {r['item_id']}: {'OK' if v.get('ficha_correcta') else 'ERROR ' + errs}  (USD {v.get('costo_usd', 0):.4f})")
    falta = sum(1 for r in fichas if not valido(hechos.get(r["item_id"], {})))
    print(f"{conjunto}: {len(hechos)} de {len(fichas)} auditadas" + (f" (faltan {falta}: volvé a correr)" if falta else ""))
    return hechos


# ----------------------------------------------------------------------------- conjuntos
def _por_id(fichas: list[dict], ids: list[str]) -> list[dict]:
    idx = {r["item_id"]: r for r in fichas}
    return [idx[i] for i in ids if i in idx]


def conjuntos_validacion() -> dict:
    final = V.cargar("final")
    esperados = [e["item_id"] for f in ("litoral_esperado.json", "andes_esperado.json")
                 for e in json.loads((RAIZ / "evals" / f).read_text(encoding="utf-8"))]
    dermalab = json.loads((RAIZ / "resultados" / "evidencia" / "P05_Dermalab_corrida_original.json").read_text(encoding="utf-8"))
    return {"dermalab_original": dermalab,                         # 18 con el nombre del bloque siguiente
            "errores_conocidos": _por_id(final, ERRORES_CONOCIDOS),  # 4 con la marca mal
            "verificadas_a_mano": _por_id(final, esperados)}        # 15 correctas (evaluador 15/15)


def muestra() -> list[dict]:
    with open(Path(__file__).resolve().parent / "muestra_auditoria.csv", encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh, delimiter=";"))
    idx = {r["item_id"]: r for r in V.cargar("final")}
    out = []
    for f in filas:
        pid = next(k for k in idx if k.split(":", 1)[1] == f["Código"])
        out.append(idx[pid])
    return out


def resumen():
    def cargar(c):
        p = SALIDAS / f"{c}.json"
        todo = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        validos = {i: v for i, v in todo.items() if v.get("lecturas_fallidas") == 0}
        if len(validos) < len(todo):
            print(f"  ({c}: {len(todo) - len(validos)} resultados de una corrida con lecturas fallidas, no se cuentan: volvé a correrlo)")
        return validos
    costo = 0.0
    d = cargar("dermalab_original")
    if d:
        det = [v for v in d.values() if not v.get("ficha_correcta")]
        nombre = [v for v in det if any(e["campo"] in ("descripcion", "variante", "tipo") and e.get("tipo") == "error" for e in v.get("errores", []))]
        print(f"Dermalab original (los 18 con error):  detectó {len(det)} de {len(d)}; {len(nombre)} señalando el nombre/descripción")
        costo += sum(v.get("costo_usd", 0) for v in d.values())
    k = cargar("errores_conocidos")
    if k:
        det = [v for v in k.values() if any(e["campo"] == "marca" and e.get("tipo") == "error" for e in v.get("errores", []))]
        print(f"Errores conocidos de marca (4):        detectó {len(det)} de {len(k)} señalando la marca")
        costo += sum(v.get("costo_usd", 0) for v in k.values())
    m = cargar("verificadas_a_mano")
    if m:
        fp = [i for i, v in m.items() if not v.get("ficha_correcta")]
        print(f"Verificadas a mano, correctas (15):    marcó como incorrectas {len(fp)} de {len(m)} {fp if fp else ''}")
        costo += sum(v.get("costo_usd", 0) for v in m.values())
    s = cargar("muestra")
    if s:
        mal = {i: v for i, v in s.items() if not v.get("ficha_correcta")}
        print(f"Muestra (53):                          {len(s) - len(mal)} correctas, {len(mal)} con algún error")
        for i, v in mal.items():
            for e in v.get("errores", []):
                if e.get("tipo") == "error":
                    print(f"    {i:<14} {e['campo']}: «{e['valor_en_ficha']}» → «{e['valor_correcto']}» | {e['cita'][:110]}")
        costo += sum(v.get("costo_usd", 0) for v in s.values())
    print(f"Costo total del auditor: USD {costo:.3f}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # consola de Windows
    except Exception:
        pass
    que = sys.argv[1] if len(sys.argv) > 1 else "resumen"
    if que == "validacion":
        for nombre, fichas in conjuntos_validacion().items():
            if len(sys.argv) > 2 and nombre != sys.argv[2]:
                continue
            correr(nombre, fichas)
    elif que == "muestra":
        correr("muestra", muestra())
    elif que == "seco":   # arma el contexto de todas las fichas sin llamar a la API (para probar)
        todas = [r for fs in conjuntos_validacion().values() for r in fs] + muestra()
        tam = [len(mensaje(r)) for r in todas]
        print(f"{len(todas)} fichas; contexto de {min(tam)} a {max(tam)} caracteres (sin el estándar)")
    elif que == "contexto":   # para inspeccionar lo que ve el auditor: python auditoria/auditor_modelo.py contexto P02:RIV-1248
        idx = {r["item_id"]: r for r in V.cargar("final")}
        print(mensaje(idx[sys.argv[2]]))
    resumen()
