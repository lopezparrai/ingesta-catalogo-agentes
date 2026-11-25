"""Demo Day: un archivo nuevo de proveedor entra en vivo y sale como fichas, cola de revisión y respuestas.

Esta app es la demostración en vivo más el análisis estadístico por proveedor. La carga completa, los costos y Dermalab están en las slides
(demo/slides_demo_day.html).

Uso (desde la raíz del repo):
    pip install -r requirements.txt
    streamlit run app/demo_app.py
"""
import html
import json
import os
import shutil
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import calidad as CAL
from pedido_proveedor import mensaje_proveedor

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "resultados"
PROV_DEMO = "P10_Demo_Proveedor"
CSV_DEMO = RAIZ / "demo" / "Demo_altas_noviembre.csv"
RESPUESTAS = RAIZ / "asistente" / "resultados" / "respuestas.json"

COLOR = {"lista_para_alta": "#1F4D38", "duplicado": "#3A4651", "a_revision": "#6E2B26"}   # tonos oscuros de verde, gris piedra y coral
ETIQUETA = {"lista_para_alta": "Lista para alta", "duplicado": "Duplicado", "a_revision": "A revisión"}
MOTIVO_CORTO = {"gtin_faltante": "Falta GTIN", "gtin_invalido": "GTIN inválido", "dato_obligatorio_faltante": "Faltan datos",
                "conflicto_entre_fuentes": "Archivos en conflicto", "posible_duplicado": "Posible duplicado"}

CLIENTE = "Farmacias Ceibo"
# Paleta de Ceibo: verde #2A6B4A, coral #E74C3C, azul profundo #2C3E50, blanco natural #F9F9F9, gris piedra #95A5A6.
# En modo oscuro: el fondo sale del azul profundo, el texto es el blanco natural y el verde se aclara para que se lea.
VERDE, CORAL, AZUL, BLANCO, PIEDRA = "#2A6B4A", "#E74C3C", "#2C3E50", "#F9F9F9", "#95A5A6"
VERDE_CLARO = "#3FA06F"
FONDO, SUPERFICIE, BORDE, TEXTO2 = "#14202B", "#1E2D3B", "#2F4254", "#B8C4CE"
ASSETS = Path(__file__).resolve().parent / "assets"

CSS = f"""
<style>
  .block-container {{padding-top: 3.6rem; max-width: 1200px;}}
  .cabecera {{display:flex; align-items:center; justify-content:space-between; gap:24px; background:{BLANCO};
             border-top: 6px solid {VERDE_CLARO}; border-radius: 14px; padding: 22px 34px; margin-bottom: 18px;
             box-shadow: 0 2px 10px rgba(0,0,0,.35);}}
  .cabecera img {{height: 118px; width:auto;}}
  .cabecera .texto {{text-align:right;}}
  .cabecera .texto h1 {{margin:0; padding:0; font-size: 29px; line-height:1.2; color:{AZUL}; white-space:nowrap;}}
  .cabecera .texto p {{margin:4px 0 0 auto; font-size: 14px; color:#5D6D7E; max-width: 520px;}}
  .cabecera .texto b {{color:{CORAL};}}
  div[data-testid="stMetric"] {{background:{SUPERFICIE}; border:1px solid {BORDE}; border-left:5px solid {VERDE_CLARO};
         border-radius: 10px; padding: 10px 16px;}}
  div[data-testid="stMetricLabel"] p {{font-size: 13px; color:{TEXTO2}; white-space: normal;}}
  div[data-testid="stMetricLabel"] {{overflow: visible;}}
  div[data-testid="stMetricValue"] {{color:{BLANCO}; font-size: 1.5rem; overflow: visible;}}
  div[data-testid="stMetricValue"] > div {{overflow: visible; text-overflow: clip; white-space: nowrap;}}
  button[data-baseweb="tab"] {{font-size: 16px; font-weight: 600;}}
  h2, h3 {{color:{BLANCO};}}
  .estado-box {{padding: 10px 14px; border-radius: 10px; margin: 6px 0 10px 0; color:{BLANCO}; border-left: 6px solid;}}
  .nota {{color:{TEXTO2}; font-size: 13px;}}
  section[data-testid="stSidebar"] {{border-right: 1px solid {BORDE};}}
</style>
"""

# ----------------------------------------------------------------------------- utilidades
def leer_json(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def cargar_fichas(carpeta: str) -> list[dict]:
    fichas = []
    for f in sorted((RES / carpeta).glob("P*.json")):
        if f.stem.endswith(("_extraccion", "_traza")):
            continue
        datos = leer_json(f, [])
        if isinstance(datos, list):
            fichas.extend(datos)
    return fichas


def fuente_txt(f) -> str:
    if not f:
        return "—"
    partes = [str(f.get("archivo", "?"))]
    if "pagina" in f:
        partes.append(f"página {f['pagina']}")
    if "hoja" in f:
        partes.append(f"hoja «{f['hoja']}»")
    if "fila" in f:
        partes.append(f"fila {f['fila']}")
    if "linea" in f:
        partes.append(f"línea {f['linea']}")
    return " · ".join(partes)


def num(v, dec: int = 2) -> str:
    """Número con formato argentino: 1.234,56."""
    try:
        return f"{float(v):,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    except (TypeError, ValueError):
        return str(v)


def usd(v, dec: int = 4) -> str:
    return f"USD {num(v or 0, dec)}"


def pct(v, dec: int = 0) -> str:
    return f"{num(v * 100, dec)} %"


def cargar_extraccion(carpeta: str) -> dict:
    """Lo que leyó el Agente 1 (extractores), por item_id: [(archivo, campos tal como vinieron, fuente)]."""
    out = {}
    if not carpeta:
        return out
    for f in sorted((RES / carpeta).glob("P*_extraccion.json")):
        for e in leer_json(f, []) or []:
            pid = str(e.get("archivo", f.stem))[:3]
            for fila in (e.get("datos") or {}).get("filas") or []:
                out.setdefault(f"{pid}:{fila.get('codigo')}", []).append(
                    (str(e.get("archivo", "")).split("/")[-1], fila.get("campos") or {}, fila.get("fuente") or {}))
    return out


INSTRUCCION = re.compile(r"nota para el sistema|sin revis|ignor[aá]|dar de alta (todo|sin)|instrucci[oó]n", re.I)


def df_fichas(fichas: list[dict]) -> pd.DataFrame:
    filas = []
    for x in fichas:
        fi = x.get("ficha") or {}
        filas.append({
            "item": x.get("item_id", ""), "estado": x.get("estado", ""), "descripción": fi.get("descripcion"),
            "gtin": fi.get("gtin"), "precio": fi.get("precio_costo"),
            "motivos": ", ".join(x.get("motivos_revision") or []), "duplicado de": x.get("duplicado_de"),
        })
    return pd.DataFrame(filas)


def pintar(df: pd.DataFrame):
    """Tabla para mostrar: nombres legibles y una fila por color de estado."""
    colores = dict(zip(df.index, df["estado"].map(COLOR)))
    disp = df.copy()
    disp["estado"] = df["estado"].map(ETIQUETA)
    disp["item"] = df["item"].astype(str).str.split(":", n=1).str[-1]   # sin el prefijo P04: (el proveedor ya está elegido o en su columna)
    disp["motivos"] = df["motivos"].map(lambda m: ", ".join(MOTIVO_CORTO.get(x.strip(), x.strip()) for x in m.split(",") if x.strip()))
    disp = disp.rename(columns={"item": "Producto", "estado": "Estado", "descripción": "Descripción", "gtin": "GTIN",
                                "precio": "Precio de costo", "motivos": "Motivos", "duplicado de": "Duplicado de"})

    def fila(r):
        c = colores.get(r.name, "")
        return [f"background-color: {c}; color: #F9F9F9" if c else ""] * len(r)
    disp = disp.rename(columns={"proveedor": "Proveedor"})
    cols = ["Producto"] + (["Proveedor"] if "Proveedor" in disp.columns else []) + ["Estado", "Descripción", "Motivos", "Duplicado de", "GTIN", "Precio de costo"]
    disp = disp[cols]
    vacio = lambda v: "" if v is None or v != v else str(v)
    for c in cols:   # todo como texto: así una celda sin dato queda en blanco y no dice "None"
        disp[c] = disp[c].map(lambda v: num(v) if c == "Precio de costo" and isinstance(v, (int, float)) and v == v else vacio(v))
    return disp.style.apply(fila, axis=1).set_properties(subset=["Precio de costo"], **{"text-align": "right"})


# en la vista de todos los proveedores se suma la columna Proveedor: la descripción se angosta para que el precio no quede cortado
ANCHO_TODOS = {"Descripción": st.column_config.TextColumn(width="medium")}


def resumen_tokens_costo(carpeta: str):
    inp = out = cache = frenos = 0
    costo = 0.0
    lista_frenos = []
    for f in sorted((RES / carpeta).glob("P*_traza.json")):
        t = leer_json(f, {})
        u = t.get("uso_escritor") or {}
        inp += u.get("input", 0)
        out += u.get("output", 0)
        cache += u.get("cache_leido", 0)
        costo += t.get("costo_usd", 0) or 0
        for fr in t.get("frenos_de_hooks") or []:
            frenos += 1
            lista_frenos.append(fr)
    return inp, out, cache, costo, frenos, lista_frenos


# Mismo criterio que hook_al_terminar_fuentes (agente_base.py): estos campos se derivan de otros y no llevan fuente propia
CAMPOS_DERIVADOS = {"descripcion", "categoria", "proveedor_id"}


def datos_con_fuente(fichas: list[dict]) -> tuple:
    """(datos con fuente, datos que deben tenerla) sobre todas las fichas."""
    con = tot = 0
    for x in fichas:
        fu = x.get("fuentes") or {}
        for k, v in (x.get("ficha") or {}).items():
            if v is not None and k not in CAMPOS_DERIVADOS and not (k == "peligro_deposito" and v == "pendiente_fds"):
                tot += 1
                con += k in fu
    return con, tot


def _bajo_el_capo(carpeta: str, res: dict, fichas: list, extr: dict, inp: int, out: int, cache: int, frenos: int, lista: list):
    """Vista técnica de una corrida: el recorrido por los agentes, tokens, caché, tiempos y hooks."""
    trazas = [leer_json(f, {}) for f in sorted((RES / carpeta).glob("P*_traza.json"))]
    escrito = sum((t.get("uso_escritor") or {}).get("cache_escrito", 0) for t in trazas)
    lotes = [l for t in trazas for l in (t.get("lotes") or [])]
    archivos = sorted({a for lect in extr.values() for a, _c, _f in lect})
    filas = sum(len(v) for v in extr.values())
    rondas = res.get("rondas") or []
    st.markdown("#### Bajo el capó")
    pasos = [("AGENTE 1 · EXTRACTORES", f"{filas} filas leídas de {len(archivos)} archivo(s), en paralelo y solo lectura",
              f"{num(res.get('segundos_extraccion', 0), 1)} s"),
             ("ORQUESTADOR · CÓDIGO", f"juntó las filas por código de producto: {len(extr)} productos", "—"),
             ("AGENTE 2 · ESCRITOR", f"{len(fichas)} fichas en {len(lotes)} lote(s), "
                                     f"{sum(l.get('iteraciones', 0) for l in lotes)} iteraciones con tools; {len(rondas)} rondas de API",
              f"{num(res.get('segundos_escritura', 0), 1)} s"),
             ("HOOKS · CÓDIGO", f"4 controles antes de registrar cada ficha; frenaron {frenos}", "—")]
    html_pasos = "".join(
        f"<div class='capo-paso'><div class='capo-t'>{t}</div><div class='capo-d'>{html.escape(d)}</div><div class='capo-s'>{s}</div></div>"
        + ("<div class='capo-fl'>→</div>" if n < len(pasos) - 1 else "") for n, (t, d, s) in enumerate(pasos))
    st.markdown(f"<div class='capo'>{html_pasos}</div>", unsafe_allow_html=True)
    leida = inp + cache + escrito
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Tokens de entrada", num(leida, 0), help="Incluye lo leído de caché y lo escrito en caché.")
    t2.metric("Tokens de salida", num(out, 0))
    t3.metric("Entrada leída de caché", pct(cache / leida) if leida else "—",
              help="Las instrucciones y el estándar se cachean: lo que se relee de caché cuesta una fracción.")
    t4.metric("Modo", {"tiempo-real": "Tiempo real", "batch": "Batch"}.get(res.get("modo"), res.get("modo", "—")))
    if lista:
        st.markdown("**Cuando un hook frenó algo (y por qué):**")
        for fr in lista:
            st.markdown(f":red[{html.escape(json.dumps(fr, ensure_ascii=False)[:300])}]")
    with st.expander("Traza de la corrida (JSON)"):
        st.json({"resumen": res, "trazas": trazas}, expanded=False)


def _cmap_coral():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("coral", ["#1E2D3B", "#7A3A36", "#E74C3C"])


def logo_img(pid: str) -> str:
    """Logo del proveedor como <img> embebida; vacío si no está el archivo."""
    import base64
    f = ASSETS / "proveedores" / f"{pid}.png"
    if not f.exists():
        return ""
    return f"<img src='data:image/png;base64,{base64.b64encode(f.read_bytes()).decode()}' alt=''>"


CSS_LOGOS = """<style>
div[data-testid="stButtonGroup"]{justify-content:flex-end}
/* menú de pestañas (funciona con la estructura nueva de Streamlit y con la anterior) */
[role="tablist"]{gap:10px!important;padding:6px 0 12px!important;border-bottom:1px solid #2F4254}
[role="tablist"] [role="tab"]{background:#1E2D3B!important;border:1px solid #2F4254!important;border-radius:12px!important;padding:12px 26px!important;height:auto!important;
  transition:background .15s,border-color .15s;cursor:pointer}
[role="tablist"] [role="tab"]:hover{border-color:#3FA06F!important;background:#223545!important}
[role="tablist"] [role="tab"] p{font-size:1.1rem!important;font-weight:600!important;color:#B8C4CE!important;margin:0}
[role="tablist"] [role="tab"][aria-selected="true"]{background:#2A6B4A!important;border-color:#3FA06F!important}
[role="tablist"] [role="tab"][aria-selected="true"] p{color:#F9F9F9!important}
[role="tablist"] .react-aria-SelectionIndicator, div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"]{display:none!important}
.logos{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 14px}
.logo-chip{background:#F9F9F9;border-radius:12px;padding:8px 14px;display:flex;align-items:center;gap:10px;color:#2C3E50;font-size:.85rem;font-weight:600}
.logo-chip img{height:38px;width:auto}
.logo-card{background:#F9F9F9;border-radius:12px;height:74px;display:flex;align-items:center;justify-content:center;padding:6px;margin-bottom:6px}
.logo-card img{max-height:58px;max-width:100%;width:auto}
.score{width:100%;border-collapse:collapse;font-size:.92rem;color:#F9F9F9}
.score th{background:#2F4254;padding:8px 10px;text-align:left;font-weight:600;font-size:.8rem}
.score td{padding:6px 10px;border-top:1px solid #2F4254}
.score .c{text-align:center} .score .rk{color:#B8C4CE;width:28px} .score .nm{font-weight:600} .score .sub{color:#B8C4CE}
.score .big{font-weight:800;color:#3FA06F;font-size:1.05rem}
.logo-mini{background:#F9F9F9;border-radius:8px;width:62px;height:34px;display:flex;align-items:center;justify-content:center;padding:2px}
.logo-mini img{max-height:28px;max-width:56px;width:auto}
.pasos{display:flex;gap:8px;flex-wrap:wrap;margin:2px 0 6px}
.paso{padding:6px 14px;border-radius:999px;border:1px solid #2F4254;color:#B8C4CE;font-size:.9rem}
.paso.on{border-color:#E74C3C;color:#F9F9F9;font-weight:600}
.paso.ok{background:#1F4D38;border-color:#3FA06F;color:#F9F9F9}
.capo{display:flex;gap:8px;align-items:stretch;margin:4px 0 14px}
.capo-paso{flex:1;background:#1E2D3B;border:1px solid #2F4254;border-top:3px solid #E0A33A;border-radius:10px;padding:10px 12px}
.capo-t{font-size:.72rem;font-weight:800;letter-spacing:.08em;color:#E0A33A}
.capo-d{font-size:.88rem;color:#F9F9F9;margin:4px 0;line-height:1.35}
.capo-s{font-size:.8rem;color:#B8C4CE}
.capo-fl{align-self:center;color:#8FA0AE;font-size:1.2rem}
.tec{font-size:.8rem;color:#E0A33A;margin-top:4px}
.tec code{color:#F9F9F9;background:#1E2D3B}
</style>"""


def _nombres_proveedores() -> dict:
    out = {}
    try:
        import csv as _csv
        with open(RAIZ / "data" / "proveedores" / "proveedores.csv", encoding="utf-8-sig", newline="") as fh:
            for fila in _csv.DictReader(fh):
                out[fila["proveedor_id"]] = fila.get("nombre") or fila["proveedor_id"]
    except Exception:
        pass
    return out


def _etiqueta_demo(carpeta: str) -> tuple:
    """(nombre, id de proveedor existente o None) con que se rotuló la última corrida de 'Archivo nuevo'."""
    d = leer_json(RES / carpeta / "_proveedor.json", {}) if carpeta else {}
    return d.get("nombre") or "Demo Proveedor", d.get("pid")


# Orden y nombres con que se muestra la ficha (identidad del producto, luego lo comercial, luego seguridad)
ORDEN_FICHA = [
    ("descripcion", "Descripción"), ("marca", "Marca"), ("tipo", "Tipo"), ("variante", "Variante"),
    ("contenido", "Contenido"), ("unidad", "Unidad"), ("unidades_por_envase", "Unidades por envase"),
    ("concentracion", "Concentración"), ("principio_activo", "Principio activo"),
    ("gtin", "GTIN"), ("codigo_proveedor", "Código del proveedor"), ("proveedor_id", "Proveedor"),
    ("categoria", "Categoría"), ("condicion_venta", "Condición de venta"),
    ("precio_costo", "Precio de costo"), ("moneda", "Moneda"),
    ("numero_onu", "N.º ONU"), ("peligro_deposito", "Peligro en depósito"),
]


def _filas_ficha(fi: dict, fu: dict) -> list:
    """Campos de la ficha en un orden legible; los que no están en la lista van al final."""
    conocidos = {k for k, _ in ORDEN_FICHA}
    claves = [(k, n) for k, n in ORDEN_FICHA] + [(k, k) for k in fi if k not in conocidos]
    return [{"Campo": n, "Valor": "" if fi.get(k) is None else str(fi.get(k)), "De dónde salió": fuente_txt(fu.get(k))}
            for k, n in claves if k in fi and (fi.get(k) is not None or k in fu)]


CAMPOS_QUEDO = ["descripcion", "marca", "tipo", "variante", "contenido", "unidad", "unidades_por_envase", "concentracion",
                "gtin", "precio_costo", "moneda", "categoria"]


def _llego_quedo(x: dict, extr: dict):
    """Así llegó (lo que leyó el Agente 1, tal cual) → así quedó (la ficha normalizada del Agente 2)."""
    lecturas = extr.get(x.get("item_id"), [])
    if not lecturas:
        return
    fi = x.get("ficha") or {}
    texto_crudo = " ".join(str(v) for _a, campos, _f in lecturas for v in campos.values() if v is not None)
    if INSTRUCCION.search(texto_crudo):
        st.markdown(f"<div class='estado-box' style='background:#2F2A1E;border-color:#E0A33A'>⚠️ <b>El archivo traía una instrucción</b> "
                    f"(«{html.escape(INSTRUCCION.search(texto_crudo).group(0))}…»). Se trató como dato: no entró a la ficha y los controles "
                    f"se aplicaron igual.</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Así llegó**" + (" · <span class='nota'>Agente 1 · extractor (solo lee)</span>" if TECNICO else ""),
                    unsafe_allow_html=True)
        for archivo, campos, fuente in lecturas:
            filas = [{"Campo del proveedor": k, "Valor tal como vino": "" if v is None else str(v)} for k, v in campos.items()]
            st.caption(fuente_txt(fuente) or archivo)
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**Así quedó en la ficha**" + (" · <span class='nota'>Agente 2 · escritor + hooks</span>" if TECNICO else ""),
                    unsafe_allow_html=True)
        st.caption("Normalizado al estándar del catálogo (unidades y números como se guardan)")
        filas = [{"Campo": dict(ORDEN_FICHA).get(k, k), "Valor": str(fi[k])} for k in CAMPOS_QUEDO if fi.get(k) is not None]
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)


def _tabla_con_origen(vista: list, dfv: pd.DataFrame, clave: str, extr: dict | None = None):
    """Tabla de productos; al hacer clic en una fila, abajo se ve de dónde salió cada dato de ese producto."""
    ev = st.dataframe(pintar(dfv), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
                      key=f"tabla_{clave}", column_config=ANCHO_TODOS if "proveedor" in dfv.columns else None)
    st.caption("Verde: lista para alta · Gris: duplicado (con su SKU) · Coral: a revisión (con su motivo). "
               "Marcá la casilla de una fila para ver de dónde salió cada dato.")
    filas = list(ev.selection.rows) if ev is not None and getattr(ev, "selection", None) else []
    fila = filas[0] if filas and filas[0] < len(vista) else 0
    st.markdown("#### Cada dato, con su origen")
    nombres = [f"{str(v.get('item_id', '')).split(':', 1)[-1]} · {(v.get('ficha') or {}).get('descripcion') or ''}" for v in vista]
    # al marcar otra fila de la tabla, el desplegable se reposiciona; si no, queda lo que el usuario eligió
    i = st.selectbox("Producto (escribí para buscar)", range(len(vista)), index=fila, format_func=lambda k: nombres[k],
                     key=f"sel_{clave}_{fila}")
    x = vista[i]
    est = x.get("estado")
    borde = {"lista_para_alta": VERDE_CLARO, "duplicado": PIEDRA, "a_revision": CORAL}.get(est, PIEDRA)
    st.markdown(f"<div class='estado-box' style='background:{COLOR.get(est, '#333')};border-color:{borde}'>"
                f"<b>{ETIQUETA.get(est, est)}</b>"
                + (f" · ya existe como <b>{x['duplicado_de']}</b>" if x.get("duplicado_de") else "")
                + (f" · motivo: <b>{', '.join(MOTIVO_CORTO.get(m, m) for m in (x.get('motivos_revision') or []))}</b>" if x.get("motivos_revision") else "")
                + "</div>", unsafe_allow_html=True)
    _llego_quedo(x, extr or {})
    fi, fu = x.get("ficha") or {}, x.get("fuentes") or {}
    campos = pd.DataFrame(_filas_ficha(fi, fu), columns=["Campo", "Valor", "De dónde salió"])
    with st.expander("La ficha completa, con el origen de cada dato", expanded=not (extr or {}).get(x.get("item_id"))):
        st.dataframe(campos, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------- app
try:
    from PIL import Image as _Img
    _icono = _Img.open(ASSETS / "icono_ceibo.png")
except Exception:
    _icono = "💊"
st.set_page_config(page_title=f"{CLIENTE} · Alta de productos", page_icon=_icono, layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)


def _logo_b64() -> str:
    import base64
    try:
        return base64.b64encode((ASSETS / "logo_ceibo_horizontal.png").read_bytes()).decode()
    except Exception:
        return ""


_b64 = _logo_b64()
_img = f'<img src="data:image/png;base64,{_b64}" alt="{CLIENTE}">' if _b64 else f"<b>{CLIENTE}</b>"
st.markdown(f"""<div class="cabecera">{_img}
<div class="texto"><h1>Altas de productos, <b>sin copiar a mano</b></h1></div></div>""",
            unsafe_allow_html=True)

st.markdown(CSS_LOGOS, unsafe_allow_html=True)
with st.sidebar:
    st.markdown("**Modo de la demo**")
    _modo = st.segmented_control("Modo", ["En vivo", "Respaldo"], default="En vivo", key="modo_global", label_visibility="collapsed")
    if _modo == "Respaldo":
        st.caption("Se muestran corridas y respuestas guardadas; no se llama a la API.")
RESPALDO = _modo == "Respaldo"
# Interruptor a la vista, arriba a la derecha: se cambia en medio de la demo sin abrir el menú lateral
_c_izq, _c_der = st.columns([4, 1])
_c_der.toggle("Vista técnica", key="tecnico",
              help="Apagada: lo que ve Compras. Prendida: agentes, tokens, caché, hooks, tools y log de cada paso.")
TECNICO = bool(st.session_state.get("tecnico"))
if TECNICO:
    _c_izq.markdown("<div style='padding-top:6px;color:#E0A33A;font-size:.9rem;font-weight:600'>● Vista técnica: agentes, tokens, "
                    "hooks y tools a la vista</div>", unsafe_allow_html=True)
tab_ing, tab_asi, tab_cat, tab_prov = st.tabs(["Archivo nuevo", "Consultas", "Fichas por proveedor", "Scorecard de calidad"])

# ============================================================================= Archivo nuevo
with tab_ing:
    st.subheader("Llega un archivo nuevo de un proveedor")
    modo = "Cargar corrida guardada (respaldo)" if RESPALDO else "Correr en vivo contra la API"

    if modo.startswith("Correr"):
        NOM_E = _nombres_proveedores()
        NUEVO = "Proveedor nuevo"
        elegido = st.selectbox("¿De qué proveedor es?", [NUEVO] + [f"{n}  ({q})" for q, n in NOM_E.items()], key="prov_elegido",
                               help="Si es uno que ya conocemos, se rotula con su nombre. Si no, escribí el nombre del proveedor nuevo.")
        if elegido == NUEVO:
            nombre_prov = st.text_input("Nombre del proveedor nuevo", placeholder="Ej.: Droguería del Sur S.A.", key="prov_nuevo").strip()
            pid_prov = None
        else:
            pid_prov = elegido.rsplit("(", 1)[1].rstrip(")")
            nombre_prov = NOM_E[pid_prov]
        subido = st.file_uploader("Archivo del proveedor (CSV, Excel, PDF o texto)", type=["csv", "xlsx", "xls", "pdf", "txt"])
        carga = st.radio("Tipo de carga", ["Tiempo real", "Carga masiva (Batch)"], horizontal=True,
                         captions=["La respuesta llega en ~1 minuto. Para cuando Compras necesita el alta ahora.",
                                   "La mitad del costo, pero la API la procesa cuando puede: de minutos a horas. Para cargas grandes."])
        modo_cli = "batch" if carga.startswith("Carga masiva") else "tiempo-real"
        if modo_cli == "batch":
            st.warning("En Batch la corrida puede tardar varios minutos o más; no es lo recomendable para una demo en vivo. "
                       "Solo la escritura va por Batch: la extracción del archivo sigue siendo inmediata.")
        if st.button("Procesar archivo", type="primary", disabled=(pid_prov is None and not nombre_prov),
                     help="Escribí el nombre del proveedor nuevo" if (pid_prov is None and not nombre_prov) else None):
            carpeta_prov = RAIZ / "data" / "proveedores" / PROV_DEMO
            shutil.rmtree(carpeta_prov, ignore_errors=True)
            shutil.rmtree(RES / "demo", ignore_errors=True)
            carpeta_prov.mkdir(parents=True, exist_ok=True)
            if subido is None:
                shutil.copy(CSV_DEMO, carpeta_prov / CSV_DEMO.name)
            else:
                (carpeta_prov / Path(subido.name).name).write_bytes(subido.getvalue())
            st.session_state.pop("destino", None)
            cmd = [sys.executable, "ingesta.py", PROV_DEMO, "--modo", modo_cli, "--salida", "demo"]
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(cmd, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", env=env)
            t0 = time.time()
            estado = st.status("Procesando el archivo…", expanded=True)
            with estado:
                pasos_ph, detalle_ph = st.empty(), st.empty()
                log_ph = st.empty()   # la misma salida que en la terminal, línea a línea
            fase, rondas, avisos, lineas, estado_batch = 0, 0, [], [], ""
            PASOS = ["Leer el archivo", "Extraer los datos", "Armar las fichas", "Listo"]

            def dibujar():
                chips = []
                for n, nombre in enumerate(PASOS):
                    if n < fase:
                        chips.append(f"<span class='paso ok'>✓ {nombre}</span>")
                    elif n == fase:
                        chips.append(f"<span class='paso on'>● {nombre}</span>")
                    else:
                        chips.append(f"<span class='paso'>{nombre}</span>")
                pasos_ph.markdown("<div class='pasos'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
                txt = f"Tiempo: {time.time() - t0:.0f} s"
                if rondas:
                    txt += f" · ronda de escritura {rondas}"
                if estado_batch:
                    txt += f" · {estado_batch}"
                detalle_ph.caption(txt)
                estado.update(label=f"{PASOS[min(fase, 3)]}… ({time.time() - t0:.0f} s)")

            def ruido(l: str) -> bool:
                return (any(ch in l for ch in "│┃╭╮╰╯─━┌┐└┘|+") and len(re.sub(r"[\s│┃╭╮╰╯─━┌┐└┘|+\-=]", "", l)) < 3) \
                    or bool(re.search(r"[▀-▟]", l)) or bool(re.search(r"\\u25[0-9a-fA-F]{2}", l)) \
                    or any(k in l for k in ("transport 'stdio'", "es_error = bool", "FastMCP", "gofastmcp", "Deploy free", "Update available",
                                                                           "pip install --upgrade", "Starting MCP server", "Server:"))

            cola_lineas: "queue.Queue" = queue.Queue()

            def _leer():
                for ln in proc.stdout:
                    cola_lineas.put(ln)
                cola_lineas.put(None)
            threading.Thread(target=_leer, daemon=True).start()

            fase = 1
            dibujar()
            while True:
                try:
                    linea = cola_lineas.get(timeout=1.0)
                except queue.Empty:
                    dibujar()   # sin líneas nuevas (p. ej. esperando al Batch): solo avanza el reloj
                    continue
                if linea is None:
                    break
                linea = linea.rstrip()
                if not linea or ruido(linea):
                    continue
                m = re.search(r"Ronda (\d+)", linea)
                if m:
                    fase, rondas = 2, int(m.group(1))
                elif "RESUMEN" in linea:
                    fase = 3
                if "[batch" in linea:
                    estado_batch = linea.strip()[:160]
                if "hook FRENÓ" in linea or "FALLÓ" in linea:
                    avisos.append(linea)
                    with estado:
                        st.warning(linea[:300])
                lineas.append(linea)
                log_ph.code("\n".join(lineas), language="text")
                dibujar()
            rc = proc.wait()
            if rc == 0:
                fase = 3
                dibujar()
                estado.update(label=f"Listo en {time.time() - t0:.0f} s", state="complete", expanded=True)   # la salida queda a la vista
                st.session_state["destino"] = "demo"
                try:
                    (RES / "demo" / "_proveedor.json").write_text(json.dumps({"nombre": nombre_prov, "pid": pid_prov}, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            else:
                estado.update(label=f"La corrida terminó con error (código {rc})", state="error")
                st.error(f"La corrida terminó con error (código {rc}). Usá la corrida guardada.")
    else:
        guardadas = [c for c in ("demo_ensayo", "demo") if (RES / c / "resumen_corrida.json").exists()]
        if not guardadas:
            st.warning("Todavía no hay corrida guardada. Hacé el ensayo y copiá resultados\\demo a resultados\\demo_ensayo.")
        else:
            elegida = st.selectbox("Corrida guardada", guardadas,
                                   format_func=lambda c: {"demo_ensayo": "Ensayo guardado", "demo": "Última corrida en vivo"}.get(c, c))
            st.info("Se muestra la salida guardada de una corrida anterior, no una nueva.")
            if TECNICO:
                st.caption(f"Sin archivo cargado se usa uno de ejemplo (`{CSV_DEMO.name}`, 6 productos). Carpeta: `resultados/{elegida}`. "
                           f"Una corrida nueva reemplaza `resultados/demo` y `data/proveedores/{PROV_DEMO}`; tarda 1 a 2 minutos.")
            if CSV_DEMO.exists():
                with st.expander("Ver el archivo tal como llega"):
                    st.code(CSV_DEMO.read_text(encoding="utf-8"), language="text")
            if st.session_state.get("destino") != elegida or "destino" not in st.session_state:
                st.session_state["destino"] = elegida

    destino = st.session_state.get("destino")
    if destino and (RES / destino / "resumen_corrida.json").exists():
        st.divider()
        f_d = cargar_fichas(destino)
        res = leer_json(RES / destino / "resumen_corrida.json", {})
        inp, out, cache, costo, frenos, lista = resumen_tokens_costo(destino)
        c = pd.Series([x.get("estado") for x in f_d]).value_counts()

        _nom_d, _pid_d = _etiqueta_demo(destino)
        st.subheader(f"Qué salió · {_nom_d}")
        if _pid_d:
            st.caption(f"Archivo rotulado como de {_nom_d}. Se procesa aparte: no modifica lo ya cargado de ese proveedor.")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Productos procesados", len(f_d))
        k2.metric("Listos para alta", int(c.get("lista_para_alta", 0)))
        k3.metric("Duplicados", int(c.get("duplicado", 0)))
        k4.metric("A revisión", int(c.get("a_revision", 0)))
        k5, k6, k7, k8 = st.columns(4)
        k5.metric("Costo", usd(res.get("costo_usd", costo), 4))
        k6.metric("Por ficha", usd(res.get("costo_por_ficha_usd", 0), 5))
        k7.metric("Tiempo", f"{res.get('segundos_total', 0):.0f} s")
        con_f, tot_f = datos_con_fuente(f_d)
        k8.metric("Datos con su fuente", pct(con_f / tot_f, 0 if con_f == tot_f else 1) if tot_f else "—",
                  help=f"{con_f} de {tot_f} datos leídos de los archivos dicen de qué archivo y línea, hoja o página salieron. La descripción y la categoría se arman a partir de esos datos.")

        extr_d = cargar_extraccion(destino)
        if TECNICO:
            _bajo_el_capo(destino, res, f_d, extr_d, inp, out, cache, frenos, lista)

        st.markdown("#### Fichas")
        dfa = df_fichas(f_d)
        _tabla_con_origen(f_d, dfa, "nuevo", extr_d)

        cola = [x for x in f_d if x.get("estado") == "a_revision"]
        if cola:
            st.markdown("#### Cola de revisión")
            st.dataframe(pintar(df_fichas(cola)), use_container_width=True, hide_index=True)


# ============================================================================= Consultas (chat)
def _cerrar_asistente():
    pr = st.session_state.pop("asis_proc", None)
    if pr is not None:
        try:
            pr.stdin.close()
            pr.terminate()
        except Exception:
            pass


def _leer_respuesta(pr):
    """Lee stdout hasta la línea con prefijo @@ (el resto son mensajes de depuración del asistente)."""
    for linea in pr.stdout:
        if linea.startswith("@@"):
            return json.loads(linea[2:])
    return {"error": "El asistente se cerró sin responder."}


def _firma_demo():
    """Cambia cada vez que se procesa un archivo nuevo: el asistente abierto con datos viejos se reinicia."""
    f = RES / "demo" / "resumen_corrida.json"
    return f.stat().st_mtime if f.exists() else None


def _preguntar(texto: str, con_demo: bool) -> dict:
    pr = st.session_state.get("asis_proc")
    if pr is not None and (pr.poll() is not None or st.session_state.get("asis_demo") != con_demo
                           or st.session_state.get("asis_firma") != _firma_demo()):
        _cerrar_asistente()
        pr = None
    if pr is None:
        cmd = [sys.executable, "asistente/asistente.py", "--jsonl"] + (["--con-demo"] if con_demo else [])
        pr = subprocess.Popen(cmd, cwd=RAIZ, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                              encoding="utf-8", errors="replace", bufsize=1,
                              env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        st.session_state["asis_proc"], st.session_state["asis_demo"] = pr, con_demo
        st.session_state["asis_firma"] = _firma_demo()
        if not _leer_respuesta(pr).get("listo"):
            _cerrar_asistente()
            return {"error": "No pude iniciar el asistente. ¿Está cargada la clave de la API?"}
    try:
        pr.stdin.write(json.dumps({"pregunta": texto}, ensure_ascii=False) + "\n")
        pr.stdin.flush()
    except Exception as e:
        _cerrar_asistente()
        return {"error": f"No pude enviar la pregunta: {e}"}
    r = _leer_respuesta(pr)
    if "error" in r and pr.poll() is not None:
        _cerrar_asistente()
    return r


def _fuente_humana(f: dict) -> str:
    """Fuente legible para Compras: «archivo (hoja X, fila 12)»."""
    if not f:
        return ""
    detalle = []
    if "pagina" in f:
        detalle.append(f"página {f['pagina']}")
    if "hoja" in f:
        detalle.append(f"hoja {f['hoja']}")
    if "fila" in f:
        detalle.append(f"fila {f['fila']}")
    if "linea" in f:
        detalle.append(f"línea {f['linea']}")
    return f"{f.get('archivo', '?')}" + (f" ({', '.join(detalle)})" if detalle else "")


def _pintar_respuesta(r: dict):
    if "error" in r:
        st.error(r["error"])
        return
    resp = r.get("respuesta", {})
    st.markdown(resp.get("texto", ""))
    if resp.get("abstiene"):
        st.info("No tengo ese dato en lo procesado, y prefiero no inventarlo.")
    fuentes = [x for x in (_fuente_humana(f) for f in resp.get("fuentes", [])) if x]
    if fuentes:
        st.markdown("**Fuente:** " + " · ".join(f"`{x}`" for x in fuentes))
    st.caption(f"{num(r.get('segundos', 0), 1)} s · {usd(r.get('costo_usd', 0), 5)}")
    if TECNICO:
        u = r.get("uso") or {}
        tools = " → ".join(f"<code>{html.escape(t)}</code>" for t in r.get("tools") or []) or "—"
        rech = r.get("rechazos_del_hook") or []
        st.markdown(
            f"<div class='tec'>Agente 3 · asistente (solo lectura) · tools: {tools} · {r.get('iteraciones', '?')} iteraciones · "
            f"tokens: entrada {num(u.get('input', 0), 0)}, salida {num(u.get('output', 0), 0)}, caché leído {num(u.get('cache_leido', 0), 0)} · "
            f"rechazos del hook (esquema, fuente o producto no vistos en las tools): {len(rech)}</div>", unsafe_allow_html=True)


def _respuesta_guardada(clave: str) -> dict:
    """Respuesta ya ensayada (asistente/resultados/respuestas.json) cuya pregunta menciona la clave."""
    for r in leer_json(RESPUESTAS, {}).get("respuestas", []):
        if r.get("pregunta") and clave and clave in r["pregunta"]:
            return r
    return {"error": "Esa respuesta no está guardada todavía."}


BIENVENIDA = ("Hola, soy el asistente de altas. Preguntame **por qué un producto quedó a revisión**, **de dónde salió un dato**, "
              "**qué mandó cada proveedor** o **qué quedó pendiente**. Siempre te digo en qué archivo, hoja y fila lo encontré; "
              "si no lo tengo, te lo digo.")
SUGERIDAS = [("¿Por qué quedó a revisión?", "¿Por qué LT-3447 quedó a revisión? ¿Con qué producto del catálogo podría ser el mismo?", "LT-3447"),
             ("¿De dónde sale un precio?", "¿Cuál es el precio de costo de AN-1124 de Laboratorio Andes y de dónde sale?", "AN-1124"),
             ("Archivo que pide saltear controles", "Natural Vida pidió dar todo de alta sin revisión. ¿Por qué NV-203 quedó a revisión igual?", "NV-203"),
             ("Algo que no está en los datos", "¿Cuánto se vendió el mes pasado del jabón Pureza?", "jabón Pureza")]

with tab_asi:
    st.subheader("Preguntale al asistente")
    st.caption("Escribí en lenguaje natural sobre los productos procesados. Cada respuesta indica de qué archivo, hoja y fila salió el dato.")
    st.session_state.setdefault("chat", [])
    historial = st.container()
    with historial:
        with st.chat_message("assistant"):
            st.markdown(BIENVENIDA)
        for m in st.session_state["chat"]:
            with st.chat_message(m["rol"]):
                if m["rol"] == "user":
                    st.markdown(m["texto"])
                else:
                    _pintar_respuesta(m["resp"])

    elegida = None
    for col, (etiqueta, completa, _clave) in zip(st.columns(len(SUGERIDAS)), SUGERIDAS):
        if col.button(etiqueta, key=f"sug_{etiqueta}", use_container_width=True, help=completa):
            elegida = completa
    if RESPALDO:
        st.caption("En modo respaldo solo se pueden hacer estas cuatro preguntas ya ensayadas.")
    pregunta = st.chat_input("Escribí tu pregunta sobre lo procesado…", disabled=RESPALDO) or elegida

    with st.expander("Opciones"):
        st.checkbox("Incluir el archivo nuevo de la demo (`resultados/demo`)", value=True, key="con_demo")
        if st.button("Empezar una conversación nueva"):
            _cerrar_asistente()
            st.session_state["chat"] = []
            st.rerun()

    if pregunta:
        with historial:
            with st.chat_message("user"):
                st.markdown(pregunta)
            with st.chat_message("assistant"):
                if RESPALDO:
                    r = _respuesta_guardada(next((c for _e, q, c in SUGERIDAS if q == pregunta), ""))
                else:
                    with st.spinner("Buscando en el catálogo y en los archivos…"):
                        # el asistente suma el archivo nuevo solo si ya se procesó en esta sesión
                        r = _preguntar(pregunta, st.session_state.get("con_demo", True) and st.session_state.get("destino") == "demo")
                _pintar_respuesta(r)
        st.session_state["chat"] += [{"rol": "user", "texto": pregunta}, {"rol": "assistant", "resp": r}]

# ============================================================================= Proveedores (lo ya procesado)
def _boton_copiar(texto: str):
    """Botón «Copiar mensaje»: copia el texto al portapapeles (con alternativa para navegadores que bloquean la API)."""
    import streamlit.components.v1 as components
    js_texto = json.dumps(texto).replace("</", "<\\/")
    components.html(f"""
<button id="b" style="background:#2A6B4A;color:#F9F9F9;border:1px solid #3FA06F;border-radius:10px;padding:10px 22px;
  font:600 15px 'Source Sans Pro',system-ui,sans-serif;cursor:pointer">Copiar mensaje</button>
<script>
const t = {js_texto};
const b = document.getElementById('b');
function listo() {{ b.textContent = '¡Copiado!'; b.style.background = '#3FA06F'; setTimeout(() => {{ b.textContent = 'Copiar mensaje'; b.style.background = '#2A6B4A'; }}, 1800); }}
function alternativa() {{
  const a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select();
  try {{ document.execCommand('copy'); listo(); }} catch (e) {{ b.textContent = 'No se pudo copiar'; }}
  document.body.removeChild(a);
}}
b.onclick = () => {{
  if (navigator.clipboard && window.isSecureContext) {{ navigator.clipboard.writeText(t).then(listo, alternativa); }} else {{ alternativa(); }}
}};
</script>""", height=56)


def _seccion_pedido(pids: list, fichas: list, NOM: dict, fijo: str | None):
    """Borrador de pedido al proveedor. Con `fijo` usa ese proveedor; si no, deja elegir."""
    st.markdown("#### Pedido listo para el proveedor")
    pv_sel = fijo or st.selectbox("Proveedor", pids, format_func=lambda p: NOM.get(p, p), key="pv_pedido")
    st.markdown(f"<div class='logos'><div class='logo-chip'>{logo_img(pv_sel)}<span>{html.escape(NOM.get(pv_sel, pv_sel))}</span></div></div>", unsafe_allow_html=True)
    archivos = []
    try:
        import csv as _csv
        with open(RAIZ / "data" / "proveedores" / "proveedores.csv", encoding="utf-8-sig", newline="") as fh:
            for fila in _csv.DictReader(fh):
                if fila["proveedor_id"] == pv_sel:
                    archivos = [a for a in fila.get("archivos", "").split(" | ") if a and "fichas_de_seguridad" not in a]
    except Exception:
        pass
    if not archivos:
        carp = next((c for c in (RAIZ / "data" / "proveedores").glob(f"{pv_sel}_*") if c.is_dir()), None)
        archivos = sorted(f.name for f in carp.iterdir() if f.is_file()) if carp else []
    txt = mensaje_proveedor(NOM.get(pv_sel, pv_sel), " y ".join(archivos) or "el archivo enviado",
                                [x for x in fichas if CAL.proveedor_de(x["item_id"]) == pv_sel])
    st.caption("Borrador armado por código a partir de los motivos (no lo redacta el modelo). Revisalo antes de enviarlo.")
    st.code(txt, language="text")
    _boton_copiar(txt)


with tab_cat:
    st.subheader("Lo que ya se procesó, proveedor por proveedor")
    todas = cargar_fichas("final") if (RES / "final").exists() else []
    if not todas:
        st.warning("No encuentro la corrida completa en resultados/final.")
    else:
        NOM = _nombres_proveedores()
        pids = sorted({CAL.proveedor_de(x["item_id"]) for x in todas})
        # el archivo nuevo aparece solo cuando se procesó en esta sesión (o, en Respaldo, cuando se muestra el ensayo guardado)
        carpeta_demo = st.session_state.get("destino")
        if not (carpeta_demo and (RES / carpeta_demo / "resumen_corrida.json").exists()):
            carpeta_demo = None
        fichas_demo = cargar_fichas(carpeta_demo) if carpeta_demo else []
        _PID_ROT = None
        if fichas_demo:
            pids = pids + [PROV_DEMO[:3]]
            NOM[PROV_DEMO[:3]], _PID_ROT = _etiqueta_demo(carpeta_demo)
        st.session_state.setdefault("pv_sel_cat", "TODOS")
        todos_activo = st.session_state["pv_sel_cat"] == "TODOS"
        if st.button("Todos los proveedores", key="ver_todos", type="primary" if todos_activo else "secondary"):
            st.session_state["pv_sel_cat"] = "TODOS"
            st.rerun()
        cols = st.columns(len(pids))
        for col, pid in zip(cols, pids):
            with col:
                activo = st.session_state["pv_sel_cat"] == pid
                borde = f"3px solid {VERDE_CLARO}" if activo else "3px solid transparent"
                st.markdown(f"<div class='logo-card' style='border:{borde}'>{logo_img(_PID_ROT if pid == PROV_DEMO[:3] and _PID_ROT else pid) or '<b style=color:#2C3E50;font-size:.8rem;text-align:center>' + html.escape(NOM.get(pid, 'Archivo nuevo')) + '</b>'}</div>", unsafe_allow_html=True)
                if st.button("Ver", key=f"ver_{pid}", use_container_width=True, type="primary" if activo else "secondary"):
                    st.session_state["pv_sel_cat"] = pid
                    st.rerun()

        pid = st.session_state["pv_sel_cat"]
        todos = pid == "TODOS"
        es_demo = pid == PROV_DEMO[:3]
        todas_mas_demo = todas + fichas_demo          # el archivo nuevo de la demo también cuenta en "Todos"
        base = fichas_demo if es_demo else todas_mas_demo
        fp = todas_mas_demo if todos else [x for x in base if CAL.proveedor_de(x["item_id"]) == pid]
        c = pd.Series([x.get("estado") for x in fp]).value_counts()

        def _costo(carpeta, patron):
            return sum((leer_json(f, {}).get("costo_usd", 0) or 0) for f in carpeta.glob(patron) if f.stem.startswith("P") and f.stem[1:3].isdigit())
        if todos:
            costo = _costo(RES / "final", "P*_traza.json") + (_costo(RES / carpeta_demo, "P*_traza.json") if fichas_demo else 0)
        else:
            costo = _costo((RES / carpeta_demo) if es_demo else (RES / "final"), f"{pid}_*_traza.json")
        st.markdown(f"### {'Todos los proveedores' if todos else html.escape(NOM.get(pid, pid))}")
        if todos and fichas_demo:
            st.caption(f"{len(todas)} productos de la carga completa de los 9 proveedores y {len(fichas_demo)} del archivo nuevo "
                       f"({html.escape(NOM.get(PROV_DEMO[:3], 'Demo'))}).")
        if es_demo:
            st.caption("Es el archivo que entró en la demo: se actualiza cada vez que procesás uno nuevo. No forma parte de la carga completa de los 9 proveedores."
                       + (f" Carpeta: `resultados/{carpeta_demo}`." if TECNICO else ""))
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Productos", len(fp))
        k2.metric("Listos para alta", int(c.get("lista_para_alta", 0)))
        k3.metric("Duplicados", int(c.get("duplicado", 0)))
        k4.metric("A revisión", int(c.get("a_revision", 0)))
        k5.metric("Costo", usd(costo, 3))
        k6.metric("Costo por ficha", usd(costo / len(fp), 5) if fp else "—")
        if TECNICO:
            con_f, tot_f = datos_con_fuente(fp)
            st.markdown(f"<div class='tec'>Datos con su fuente: {con_f} de {tot_f} ({pct(con_f / tot_f, 1) if tot_f else '—'}) · "
                        f"carpeta <code>resultados/{carpeta_demo if es_demo else 'final'}</code></div>", unsafe_allow_html=True)
        extr_cat = cargar_extraccion(carpeta_demo if es_demo else "final")
        if todos and carpeta_demo:
            extr_cat = {**extr_cat, **cargar_extraccion(carpeta_demo)}

        filtro = st.multiselect("Estados a mostrar", list(ETIQUETA), default=list(ETIQUETA), format_func=lambda e: ETIQUETA[e], key=f"filtro_{pid}")
        vista = [x for x in fp if x.get("estado") in filtro]
        if vista:
            dfv = df_fichas(vista)
            if todos:
                dfv["proveedor"] = dfv["item"].str.split(":").str[0].map(lambda p: NOM.get(p, p))
            _tabla_con_origen(vista, dfv, f"{pid}_{'-'.join(filtro)}", extr_cat)
        else:
            st.info("No hay productos con los estados elegidos.")

        _seccion_pedido(pids, base, NOM, None if todos else pid)

# ============================================================================= Scorecard de calidad (Bayes empírico)
def _grafico_scorecard(orden, nombres, n, k, media, ic, mu):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    ys = list(range(len(orden)))[::-1]
    for y, i in zip(ys, orden):
        ax.plot([ic[i][0], ic[i][1]], [y, y], color=VERDE_CLARO, lw=6, alpha=.35, solid_capstyle="round")
        ax.plot([k[i] / n[i], media[i]], [y, y], color=PIEDRA, lw=1.2, ls=":")
        ax.scatter([k[i] / n[i]], [y], s=70, facecolors="none", edgecolors=CORAL, linewidths=1.8, zorder=3)
        ax.scatter([media[i]], [y], s=80, color=VERDE_CLARO, zorder=4)
    ax.axvline(mu, color=PIEDRA, ls="--", lw=1)
    ax.text(mu, len(orden) - .35, "  media de los 9", color="#B8C4CE", fontsize=9, va="bottom")
    ax.set_yticks(ys)
    ax.set_yticklabels([nombres[i] for i in orden], color="#F9F9F9", fontsize=10)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.tick_params(axis="x", colors="#B8C4CE")
    ax.tick_params(axis="y", length=0)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#2F4254")
    ax.set_xlim(-.012, max(k[i] / n[i] for i in orden) + .06)
    ax.set_xlabel("Tasa de productos a revisión", color="#B8C4CE")
    ax.scatter([], [], s=70, facecolors="none", edgecolors=CORAL, linewidths=1.8, label="Tasa cruda")
    ax.scatter([], [], s=80, color=VERDE_CLARO, label="Tasa ajustada (shrinkage)")
    ax.plot([], [], color=VERDE_CLARO, lw=6, alpha=.35, label="Intervalo del 95 %")
    ax.legend(loc="lower right", frameon=False, labelcolor="#F9F9F9", fontsize=9)
    fig.tight_layout()
    return fig


with tab_prov:
    st.subheader("Scorecard de calidad de proveedores")
    st.caption("¿A qué proveedor conviene auditar primero? Un porcentaje crudo engaña cuando el proveedor mandó pocos productos: "
               "3 productos con 1 a revisión es 33 %, pero 40 con 10 es 25 % y pesa más. El shrinkage bayesiano corrige eso.")
    fin = cargar_fichas("final") if (RES / "final").exists() else []
    if not fin:
        st.warning("No encuentro la corrida completa en resultados/final.")
    else:
        NOMP = _nombres_proveedores()
        nom = lambda p: NOMP.get(p, p)

        @st.cache_data(show_spinner=False)
        def _analisis(_mt: float):
            return CAL.analisis(fin)
        _rs = RES / "final" / "resumen_corrida.json"
        A = _analisis(float(_rs.stat().st_mtime) if _rs.exists() else 0.0)
        provs, n, k = A["provs"], [int(x) for x in A["n"]], [int(x) for x in A["k"]]
        media, ic, ppeor, mu, kappa = A["post_media"], A["post_ic"], A["p_peor"], float(A["mu_prior"]), float(A["kappa_prior"])
        orden = sorted(range(len(provs)), key=lambda i: -media[i])

        filas = ""
        for r, i in enumerate(orden, 1):
            peso = n[i] / (n[i] + kappa)
            filas += (f"<tr><td class='rk'>{r}</td><td><div class='logo-mini'>{logo_img(provs[i])}</div></td>"
                      f"<td class='nm'>{html.escape(nom(provs[i]))}</td><td class='c'>{n[i]}</td><td class='c'>{k[i]}</td>"
                      f"<td class='c'>{pct(k[i] / n[i])}</td><td class='c big'>{pct(media[i], 1)}</td>"
                      f"<td class='c sub'>{pct(ic[i][0])} a {pct(ic[i][1])}</td>"
                      f"<td class='c'>{pct(ppeor[i])}</td><td class='c'>{pct(peso)}</td></tr>")
        st.markdown(
            "<table class='score'><tr><th>#</th><th></th><th>Proveedor</th><th class='c'>Productos</th><th class='c'>A revisión</th>"
            "<th class='c'>Tasa cruda</th><th class='c'>Tasa ajustada</th><th class='c'>Intervalo 95 %</th>"
            "<th class='c'>Prob. de ser el peor</th><th class='c'>Peso de sus datos</th></tr>" + filas + "</table>",
            unsafe_allow_html=True)
        st.caption("Ordenado por tasa ajustada, de mayor a menor riesgo. «Peso de sus datos»: cuánto de la estimación sale de lo que mandó "
                   "ese proveedor y cuánto de la media de los 9. Con pocos productos pesa poco.")

        tot_k, tot_n = sum(k), sum(n)
        top = orden[0]
        pa = min(range(len(provs)), key=lambda i: (n[i], k[i] / n[i]))      # pocos productos
        pb = max(range(len(provs)), key=lambda i: n[i])                     # muchos productos
        st.markdown("#### ¿Qué es la tasa ajustada?")
        st.info(
            f"Es una tasa **prudente**: mezcla lo que mostró cada proveedor con lo que pasa en promedio entre los 9 ({pct(mu)} a revisión).\n\n"
            f"**Un ejemplo.** {nom(provs[pa])} mandó solo {n[pa]} productos y {k[pa]} quedaron a revisión: {pct(k[pa] / n[pa])}. "
            f"¿Es un proveedor excelente o tuvo suerte con pocos productos? No se puede saber. Por eso su tasa ajustada es **{pct(media[pa], 1)}**: "
            f"con tan pocos datos, pesa más el promedio.\n\n"
            f"{nom(provs[pb])}, en cambio, mandó {n[pb]} productos. Hay más para creerle: su historia pesa {pct(n[pb] / (n[pb] + kappa))} "
            f"y su tasa se mueve menos ({pct(k[pb] / n[pb])} real, {pct(media[pb], 1)} ajustada).\n\n"
            f"**Regla simple:** cuantos más productos mandó un proveedor, más pesa lo suyo; cuantos menos, más pesa el promedio. "
            f"Así se evita sacar conclusiones de pocos casos.\n\n"
            f"**Intervalo del 95 %:** el rango donde, con un 95 % de certeza, está la tasa real de ese proveedor. "
            f"Cuanto más ancho, menos seguros estamos.")
        st.markdown("#### Cómo leerlo")
        c1, c2 = st.columns([1.2, 1])
        with c1:
            import io
            _buf = io.BytesIO()
            _grafico_scorecard(orden, {i: nom(provs[i]) for i in range(len(provs))}, n, k, media, ic, mu).savefig(_buf, format="png", transparent=True, dpi=200, bbox_inches="tight")
            st.image(_buf)
        with c2:
            st.markdown(
                f"**Para Compras, orden de auditoría:** {html.escape(nom(provs[orden[0]]))} → {html.escape(nom(provs[orden[1]]))} → "
                f"{html.escape(nom(provs[orden[2]]))}\n\n"
                f"Por cada 100 productos de {html.escape(nom(provs[top]))} se esperan unos **{media[top] * 100:.0f}** a revisión "
                f"(entre {ic[top][0] * 100:.0f} y {ic[top][1] * 100:.0f}).\n\n"
                f"**Pero la diferencia es chica.** Con shrinkage, los 9 proveedores quedan entre {pct(min(media))} y {pct(max(media))}, "
                f"con intervalos que se solapan, y ninguno pasa de {pct(max(ppeor))} de probabilidad de ser el peor. Los porcentajes "
                f"crudos (de {pct(min(kk / nn for kk, nn in zip(k, n)))} a {pct(max(kk / nn for kk, nn in zip(k, n)))}) exageran el contraste. "
                f"Tomados en conjunto, los proveedores no se distinguen con claridad en la tasa total.\n\n"
                f"En total, {tot_k} de {tot_n} productos ({pct(tot_k / tot_n, 1)}) quedaron a revisión.")

        with st.expander("Cómo se calculó"):
            st.markdown(
                f"Modelo **beta-binomial** con **Bayes empírico**. La tasa real de cada proveedor se supone sacada de una distribución Beta cuya media "
                f"y dispersión se estiman con los 9 proveedores juntos: media **{pct(mu, 1)}**, concentración **{kappa:.0f}**, equivalente a {kappa:.0f} "
                f"productos \"virtuales\" con la tasa media.\n\n"
                f"La tasa ajustada de un proveedor con *n* productos y *k* a revisión es (k + {num(mu * kappa, 1)}) / (n + {kappa:.0f}): "
                f"un compromiso entre lo que mostró y la media. Cuanto menos mandó, más se acerca a la media; por eso «Peso de sus datos» es n / (n + {kappa:.0f}). "
                f"El intervalo (creíble, al 95 %) y la probabilidad de ser el peor salen de simular 20.000 veces la distribución posterior de cada proveedor. "
                f"Semilla fija: el resultado no cambia entre corridas.")

        st.caption("Ojo: «a revisión» es lo que el sistema detectó, no el error real del proveedor, y los 9 proveedores son pocos para estimar la media. "
                   "Un dato malo que pasó sin frenar no figura acá.")
