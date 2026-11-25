"""M6 — Prueba offline del motor de rondas de ingesta.py (sin API, sin MCP): un cliente y una sesión falsos."""
import asyncio, copy, json, sys
from types import SimpleNamespace as NS

import nucleo as A
import ingesta as L


class Bloque:
    def __init__(self, **kw): self.__dict__.update(kw)
    def model_dump(self, exclude_none=True): return dict(self.__dict__)

def msg(stop, *bloques):
    u = NS(input_tokens=1000, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=800)
    return NS(stop_reason=stop, content=list(bloques), usage=u)

def tool(i, nombre, entrada): return Bloque(type="tool_use", id=i, name=nombre, input=entrada)
def texto(t): return Bloque(type="text", text=t)

class SesionFalsa:
    async def call_tool(self, nombre, entrada):
        return NS(content=[NS(text=json.dumps({"valido": True}))], is_error=False)

def ficha_real():
    import prueba_hooks
    return copy.deepcopy(prueba_hooks.BASE)

async def main():
    base = ficha_real()
    malo = copy.deepcopy(base); malo["item_id"] = "P01:X1"; malo["ficha"]["moneda"] = "DOLARES"
    bueno = copy.deepcopy(base); bueno["item_id"] = "P01:X1"
    conv = L.Conv(cid="P01-lote0", carpeta="P01_X", esperados=["P01:X1"], mensajes=[{"role": "user", "content": "hola"}])
    s = SesionFalsa()
    # ronda 1: valida un GTIN con una tool y trata de registrar una ficha mala -> el hook la frena
    await L.avanzar(conv, msg("tool_use", tool("a", "validar_gtin_tool", {"gtin": "1"}), tool("b", "registrar_ficha", malo)), s, 0.5)
    assert conv.estado == "activa" and len(conv.frenos) == 1 and not conv.fichas, (conv.estado, conv.frenos)
    ultimo = conv.mensajes[-1]["content"]
    assert ultimo[1]["is_error"] and "esquema" in ultimo[1]["content"], ultimo
    # ronda 2: la corrige
    await L.avanzar(conv, msg("tool_use", tool("c", "registrar_ficha", bueno)), s, 0.5)
    assert "P01:X1" in conv.fichas and conv.estado == "activa"
    # ronda 3: termina
    await L.avanzar(conv, msg("end_turn", texto("Listo: 1 lista_para_alta")), s, 0.5)
    assert conv.estado == "terminada", (conv.estado, conv.nota)
    assert conv.costo_usd > 0 and conv.iteraciones == 2
    print("[OK ] ficha mala frenada por hook_esquema, corregida y registrada; la conversación termina")

    # termina sin registrar todo -> el código la manda de vuelta
    c2 = L.Conv(cid="P01-lote1", carpeta="P01_X", esperados=["P01:X2"], mensajes=[{"role": "user", "content": "hola"}])
    await L.avanzar(c2, msg("end_turn", texto("listo")), s, 1.0)
    assert c2.estado == "activa" and "Todavía no registraste" in c2.mensajes[-1]["content"]
    print("[OK ] terminar sin registrar todos los productos no se permite")

    # un precio que la extracción trae y la ficha perdió: el código lo devuelve al modelo (hook_no_perder_precio)
    assert L.tiene_precio({"observaciones": [{"campos": {"P. COSTO": 104.24}}]})
    assert L.tiene_precio({"observaciones": [{"campos": {"precio": "68,91"}}]})
    assert not L.tiene_precio({"observaciones": [{"campos": {"descripcion": "X", "precio": None}}]})
    sin = copy.deepcopy(base); sin["item_id"] = "P01:X4"
    sin["estado"] = "a_revision"; sin["motivos_revision"] = ["dato_obligatorio_faltante"]
    sin["ficha"]["precio_costo"] = None; sin["fuentes"].pop("precio_costo", None)
    con = copy.deepcopy(base); con["item_id"] = "P01:X4"
    c4 = L.Conv(cid="c4", carpeta="P01_X", esperados=["P01:X4"], con_precio={"P01:X4"},
                mensajes=[{"role": "user", "content": "hola"}])
    await L.avanzar(c4, msg("tool_use", tool("p", "registrar_ficha", sin)), s, 0.5)
    await L.avanzar(c4, msg("end_turn", texto("listo")), s, 0.5)
    assert c4.estado == "activa" and c4.reintentos_precio == 1 and "precio_costo vacío" in c4.mensajes[-1]["content"], c4.estado
    await L.avanzar(c4, msg("tool_use", tool("q", "registrar_ficha", con)), s, 0.5)
    await L.avanzar(c4, msg("end_turn", texto("listo")), s, 0.5)
    assert c4.estado == "terminada" and c4.fichas["P01:X4"]["ficha"]["precio_costo"] is not None
    print("[OK ] precio perdido en el traspaso: el hook lo devuelve al modelo y la ficha se corrige")

    # una FDS sin sección 14 se le devuelve al extractor (la extracción no puede perder el dato de transporte)
    fds_mala = {"tipo_archivo": "fds", "fds": {"codigos_comerciales": ["X"], "seccion_14": {"numero_onu": None, "clase": None, "texto": None}}}
    try:
        L.O.validar_extraccion(fds_mala); raise SystemExit("la FDS sin sección 14 debía rechazarse")
    except ValueError as e:
        assert "sección 14" in str(e)
    fds_ok = {"tipo_archivo": "fds", "fds": {"codigos_comerciales": ["X"], "seccion_14": {"numero_onu": None, "clase": None, "texto": "No regulado para el transporte."}}}
    L.O.validar_extraccion(fds_ok)
    print("[OK ] FDS sin sección 14 rechazada en la extracción; 'no regulado' sí se acepta")

    # negativa y stop_reason raro -> fallida, sin explotar
    c3 = L.Conv(cid="c3", carpeta="P01_X", esperados=["P01:X3"], mensajes=[{"role": "user", "content": "hola"}])
    await L.avanzar(c3, msg("refusal"), s, 1.0)
    assert c3.estado == "fallida"
    print("[OK ] refusal -> la conversación falla con su motivo")

    # límite de iteraciones
    c4 = L.Conv(cid="c4", carpeta="P01_X", esperados=["P01:X4"], mensajes=[{"role": "user", "content": "hola"}])
    for i in range(L.MAX_ITERACIONES + 1):
        if c4.estado != "activa": break
        await L.avanzar(c4, msg("tool_use", tool(f"t{i}", "validar_gtin_tool", {"gtin": "1"})), s, 1.0)
    assert c4.estado == "fallida" and "límite" in c4.nota
    print("[OK ] límite de iteraciones")

    # serialización del historial (bloques del SDK -> dict) para el batch
    ser = L.mensajes_serializables(conv.mensajes)
    json.dumps(ser)
    print("[OK ] el historial se serializa a JSON para el batch")

    # permisos: el escritor no tiene tools de lectura de archivos
    c5 = L.Conv(cid="c5", carpeta="P01_X", esperados=["P01:X5"], mensajes=[{"role": "user", "content": "hola"}])
    await L.avanzar(c5, msg("tool_use", tool("z", "leer_excel", {"archivo": "a.xlsx"})), s, 1.0)
    assert "permiso" in c5.mensajes[-1]["content"][0]["content"]
    print("[OK ] permisos del escritor aplicados también en el motor de rondas")

def prueba_batch_falso():
    # el join es custom_id, no la posición; un batch terminado puede traer resultados mezclados
    class Lotes:
        def create(self, requests): return NS(id="b1", processing_status="in_progress", request_counts=NS(processing=3, succeeded=0, errored=0, expired=0, canceled=0))
        def retrieve(self, i): return NS(id=i, processing_status="ended", request_counts=NS(processing=0, succeeded=2, errored=1, expired=0, canceled=0))
        def results(self, i):
            yield NS(custom_id="B", result=NS(type="succeeded", message="mB"))   # fuera de orden a propósito
            yield NS(custom_id="C", result=NS(type="errored", error="overloaded"))
            yield NS(custom_id="A", result=NS(type="succeeded", message="mA"))
        def cancel(self, i): pass
    A.client = NS(messages=NS(batches=Lotes()))
    res, info = L.ronda_batch([{"custom_id": x} for x in "ABC"], 1)
    assert res["A"] == ("ok", "mA") and res["B"] == ("ok", "mB") and res["C"][0] == "error", res
    assert info["batch_id"] == "b1" and info["error"] == 1
    print("[OK ] batch con resultados fuera de orden y uno errored: se emparejan por custom_id")

asyncio.run(main())
prueba_batch_falso()
print("\nMotor de rondas: todo como se esperaba")
