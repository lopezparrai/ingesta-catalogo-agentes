"""Demo Day: ingesta de catálogo con agentes. App de Streamlit (solo muestra; no cambia el sistema).

Uso (desde la raíz del repo):
    pip install streamlit pandas
    streamlit run app/demo_app.py

Todo lo que se ve sale de resultados/ (fichas, trazas, resumen) y asistente/resultados/respuestas.json.
La pestaña Ingesta puede correr el archivo nuevo en vivo o cargar la corrida guardada (modo demo).
"""
import html
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calidad as CAL

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "resultados"
PROV_DEMO = "P10_Demo_Proveedor"
CSV_DEMO = RAIZ / "demo" / "Demo_altas_noviembre.csv"
RESPUESTAS = RAIZ / "asistente" / "resultados" / "respuestas.json"

COLOR = {"lista_para_alta": "#1F4D38", "duplicado": "#3A4651", "a_revision": "#6E2B26"}   # tonos oscuros de verde, gris piedra y coral
ETIQUETA = {"lista_para_alta": "Lista para alta", "duplicado": "Duplicado", "a_revision": "A revisión"}

# Lo que dice el guion (demo/GUION_DEMO.md). El modelo no es determinista: es lo esperado, no una promesa.
ESPERADO_DEMO = {
    "DM-001": ("lista_para_alta", None, "Producto nuevo, GTIN válido"),
    "DM-002": ("duplicado", None, "GTIN que ya está en el catálogo (SKU100014)"),
    "DM-003": ("a_revision", "gtin_invalido", "GTIN con dígito verificador inválido"),
    "DM-004": ("a_revision", "posible_duplicado", "Sin EAN; es el SH. BRISA COLOR 400ML. escrito distinto"),
    "DM-005": ("lista_para_alta", None, "0,5 LT y precio '1.234,56'"),
    "DM-006": ("a_revision", "gtin", "GTIN inválido + texto que pide dar de alta sin revisar"),
}

# Evaluación contra fichas verificadas a mano (python evaluador.py, evals/andes_esperado.json y litoral_esperado.json).
# Andes: ficha 7/7, fuente 4/7. Litoral: ficha 8/8, fuente 8/8.
EVAL_FICHA = (15, 15)
EVAL_FUENTE = (12, 15)



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
             border-top: 6px solid {VERDE_CLARO}; border-radius: 12px; padding: 14px 26px; margin-bottom: 16px;
             box-shadow: 0 2px 10px rgba(0,0,0,.35);}}
  .cabecera img {{height: 72px; width:auto;}}
  .cabecera .texto {{text-align:right;}}
  .cabecera .texto h1 {{margin:0; padding:0; font-size: 25px; line-height:1.2; color:{AZUL};}}
  .cabecera .texto p {{margin:4px 0 0 auto; font-size: 14px; color:#5D6D7E; max-width: 520px;}}
  .cabecera .texto b {{color:{CORAL};}}
  div[data-testid="stMetric"] {{background:{SUPERFICIE}; border:1px solid {BORDE}; border-left:5px solid {VERDE_CLARO};
         border-radius: 10px; padding: 10px 16px;}}
  div[data-testid="stMetricLabel"] p {{font-size: 13px; color:{TEXTO2}; white-space: normal;}}
  div[data-testid="stMetricLabel"] {{overflow: visible;}}
  div[data-testid="stMetricValue"] {{color:{BLANCO}; font-size: 1.75rem;}}
  button[data-baseweb="tab"] {{font-size: 16px; font-weight: 600;}}
  h2, h3 {{color:{BLANCO};}}
  .estado-box {{padding: 10px 14px; border-radius: 10px; margin: 6px 0 10px 0; color:{BLANCO}; border-left: 6px solid;}}
  .nota {{color:{TEXTO2}; font-size: 13px;}}
  section[data-testid="stSidebar"] {{border-right: 1px solid {BORDE};}}
</style>
"""

# ----------------------------------------------------------------------------- utilidades
def wilson(k: int, n: int, z: float = 1.96):
    """Intervalo de Wilson al 95 % para una proporción k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centro - mitad), min(1.0, centro + mitad))


def n_auditoria(N: int, tasa: float = 0.05, conf: float = 0.95) -> int:
    """Fichas a auditar de un lote de N para que, si no se encuentra ningún error, se pueda afirmar con `conf`
    de confianza que la tasa de error del lote es menor que `tasa` (muestreo sin reposición, hipergeométrica)."""
    D = math.ceil(tasa * N)          # cantidad de fichas malas a partir de la cual el lote "no pasa"
    if D <= 0 or N <= 0:
        return 0
    for n in range(1, N + 1):
        if math.comb(N - D, n) / math.comb(N, n) <= 1 - conf:
            return n
    return N


def leer_json(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def carpetas_con_fichas() -> list[str]:
    return [d.name for d in sorted(RES.iterdir()) if d.is_dir() and (d / "resumen_corrida.json").exists()]


@st.cache_data(show_spinner=False)
def cargar_fichas(carpeta: str, _mtime: float) -> list[dict]:
    fichas = []
    for f in sorted((RES / carpeta).glob("P*.json")):
        if f.stem.endswith(("_extraccion", "_traza")):
            continue
        datos = leer_json(f, [])
        if isinstance(datos, list):
            fichas.extend(datos)
    return fichas


def mtime(carpeta: str) -> float:
    p = RES / carpeta / "resumen_corrida.json"
    return p.stat().st_mtime if p.exists() else 0.0


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


def df_fichas(fichas: list[dict]) -> pd.DataFrame:
    filas = []
    for x in fichas:
        fi = x.get("ficha") or {}
        filas.append({
            "item": x.get("item_id", ""),
            "estado": x.get("estado", ""),
            "descripción": fi.get("descripcion"),
            "gtin": fi.get("gtin"),
            "precio": fi.get("precio_costo"),
            "motivos": ", ".join(x.get("motivos_revision") or []),
            "duplicado de": x.get("duplicado_de"),
        })
    return pd.DataFrame(filas)


MOTIVO_CORTO = {"gtin_faltante": "Falta EAN", "gtin_invalido": "EAN inválido", "dato_obligatorio_faltante": "Faltan datos",
                "conflicto_entre_fuentes": "Archivos en conflicto", "posible_duplicado": "Posible duplicado"}


def pintar(df: pd.DataFrame):
    """Tabla para mostrar: nombres legibles y una fila por color de estado."""
    colores = dict(zip(df.index, df["estado"].map(COLOR)))
    disp = df.copy()
    disp["estado"] = df["estado"].map(ETIQUETA)
    disp["motivos"] = df["motivos"].map(lambda m: ", ".join(MOTIVO_CORTO.get(x.strip(), x.strip()) for x in m.split(",") if x.strip()))
    disp = disp.rename(columns={"item": "Producto", "estado": "Estado", "descripción": "Descripción", "gtin": "GTIN",
                                "precio": "Precio de costo", "motivos": "Motivos", "duplicado de": "Duplicado de"})

    def fila(r):
        c = colores.get(r.name, "")
        return [f"background-color: {c}; color: #F9F9F9" if c else ""] * len(r)
    return disp.style.apply(fila, axis=1).format({"Precio de costo": "{:.2f}"}, na_rep="")


def metricas_estados(fichas: list[dict]):
    c = pd.Series([x.get("estado") for x in fichas]).value_counts()
    a, b, d = st.columns(3)
    a.metric("Listas para alta", int(c.get("lista_para_alta", 0)))
    b.metric("Duplicados", int(c.get("duplicado", 0)))
    d.metric("A revisión", int(c.get("a_revision", 0)))


def resumen_tokens_costo(carpeta: str):
    """Suma costo, tokens del escritor y frenos de hooks de las trazas de una corrida."""
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


def _cmap_coral():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("coral", ["#1E2D3B", "#7A3A36", "#E74C3C"])


# ----------------------------------------------------------------------------- app
try:
    from PIL import Image as _Img
    _icono = _Img.open(ASSETS / "icono_ceibo.png")
except Exception:
    _icono = "💊"
st.set_page_config(page_title=f"{CLIENTE} · Alta de productos", page_icon=_icono, layout="wide")
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
<div class="texto"><h1>Altas de productos, <b>sin copiar a mano</b></h1>
<p>El archivo del proveedor entra tal como llega y sale como fichas listas, duplicados detectados y una cola de revisión con su motivo.</p></div></div>""",
            unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Datos a mostrar")
    opciones = carpetas_con_fichas()
    if not opciones:
        st.error("No hay corridas en resultados/.")
        st.stop()
    carpeta = st.selectbox("Corrida", opciones,
                           index=opciones.index("final") if "final" in opciones else 0)
    st.caption("`final`: los 9 proveedores por Batch.  `demo`: el archivo nuevo en vivo.  "
               "`demo_ensayo`: el respaldo del ensayo.")

def _cargar_nombres() -> dict:
    import csv as _csv
    try:
        with open(RAIZ / "data" / "proveedores" / "proveedores.csv", encoding="utf-8-sig", newline="") as fh:
            return {f["proveedor_id"]: f for f in _csv.DictReader(fh)}
    except Exception:
        return {}


NOMBRES = _cargar_nombres()
nom = lambda p: (NOMBRES.get(p, {}).get("nombre") or p)

fichas = cargar_fichas(carpeta, mtime(carpeta))
_r = leer_json(RES / carpeta / "resumen_corrida.json", {})
_c = pd.Series([x.get("estado") for x in fichas]).value_counts()
k1, k2, k3, k4, k5 = st.columns([1, 1, 1, 1, 1.6])
k1.metric("Procesados", len(fichas))
k2.metric("Listos para alta", int(_c.get("lista_para_alta", 0)))
k3.metric("Duplicados", int(_c.get("duplicado", 0)))
k4.metric("Para revisar", int(_c.get("a_revision", 0)))
k5.metric("Costo por producto", f"USD {_r.get('costo_por_ficha_usd', 0):.5f}")
st.write("")
tab_ing, tab_fic, tab_asi, tab_cos, tab_prov, tab_conf = st.tabs(
    ["Archivo nuevo", "Fichas y revisión", "Consultas", "Costos", "Proveedores", "Confianza"])

# ============================================================================= 1. Ingesta
with tab_ing:
    st.subheader("Llega un archivo nuevo de un proveedor")
    modo = st.radio("Modo", ["Cargar corrida guardada (modo demo)", "Correr en vivo contra la API"],
                    horizontal=True)
    st.write("Archivo: `demo/Demo_altas_noviembre.csv` (6 productos: un nuevo, un duplicado, dos GTIN inválidos, "
             "un posible duplicado sin EAN y un caso de formatos).")
    if CSV_DEMO.exists():
        with st.expander("Ver el archivo tal como llega"):
            st.code(CSV_DEMO.read_text(encoding="utf-8"), language="text")

    destino = None
    if modo.startswith("Cargar"):
        guardadas = [c for c in ("demo_ensayo", "demo") if (RES / c / "resumen_corrida.json").exists()]
        if not guardadas:
            st.warning("Todavía no hay corrida guardada. Hacé el ensayo y copiá resultados\\demo a resultados\\demo_ensayo.")
        else:
            destino = st.selectbox("Corrida guardada", guardadas)
            st.info("Se muestra la salida guardada de una corrida anterior, no una nueva.")
    else:
        st.warning("Esto llama a la API y borra la salida anterior de `resultados/demo` y de `data/proveedores/"
                   f"{PROV_DEMO}` para que el archivo entre como nuevo. Tarda 1 a 2 minutos.")
        subido = st.file_uploader("Archivo del proveedor (CSV, Excel, PDF o texto)", type=["csv", "xlsx", "xls", "pdf", "txt"])
        if subido is None:
            st.caption(f"Sin archivo cargado se usa el de la demo (`{CSV_DEMO.name}`).")
        ok = st.checkbox("Entendido, correr en vivo")
        if st.button("Correr ingesta", type="primary", disabled=not ok):
            carpeta_prov = RAIZ / "data" / "proveedores" / PROV_DEMO
            shutil.rmtree(carpeta_prov, ignore_errors=True)
            shutil.rmtree(RES / "demo", ignore_errors=True)
            carpeta_prov.mkdir(parents=True, exist_ok=True)
            if subido is None:
                shutil.copy(CSV_DEMO, carpeta_prov / CSV_DEMO.name)
            else:
                (carpeta_prov / Path(subido.name).name).write_bytes(subido.getvalue())
            st.session_state["corrida_es_demo"] = subido is None
            cmd = [sys.executable, "ingesta.py", PROV_DEMO, "--modo", "tiempo-real", "--salida", "demo"]
            st.code(" ".join(cmd), language="text")
            caja = st.empty()
            lineas: list[str] = []
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(cmd, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", env=env)
            for linea in proc.stdout:
                linea = linea.rstrip()
                if not linea:
                    continue
                esc = html.escape(linea)
                if "hook FRENÓ" in linea or "FALLÓ" in linea:
                    esc = f"<span style='color:#d62728;font-weight:600'>{esc}</span>"
                lineas.append(esc)
                caja.markdown("<pre style='font-size:12px;line-height:1.35'>" + "\n".join(lineas[-30:]) + "</pre>",
                              unsafe_allow_html=True)
            rc = proc.wait()
            if rc == 0:
                st.success("Terminó. Elegí la carpeta `demo` en la barra lateral para ver las fichas.")
                destino = "demo"
            else:
                st.error(f"La corrida terminó con error (código {rc}). Usá la corrida guardada.")

    if destino:
        f_d = cargar_fichas(destino, mtime(destino))
        res = leer_json(RES / destino / "resumen_corrida.json", {})
        metricas_estados(f_d)
        inp, out, cache, costo, frenos, lista = resumen_tokens_costo(destino)
        a, b, c, d = st.columns(4)
        a.metric("Costo", f"USD {res.get('costo_usd', costo):.4f}")
        b.metric("Por ficha", f"USD {res.get('costo_por_ficha_usd', 0):.5f}")
        c.metric("Tokens (escritor)", f"{inp + out:,}".replace(",", "."), help=f"entrada {inp}, salida {out}, caché leído {cache}")
        d.metric("Frenos de hooks", frenos)
        st.write(f"Tiempo total: **{res.get('segundos_total', '?')} s** "
                 f"(extracción {res.get('segundos_extraccion', '?')} s, escritura {res.get('segundos_escritura', '?')} s)")
        if lista:
            st.markdown("**Cuando un hook frenó algo (y por qué):**")
            for fr in lista:
                st.markdown(f":red[{html.escape(json.dumps(fr, ensure_ascii=False)[:300])}]")

        if st.session_state.get("corrida_es_demo", True):
            st.markdown("**Qué se esperaba de cada producto y qué salió** (el modelo no es determinista: lo esperado no es una promesa)")
            filas = []
            for cod, (est, motivo, nota) in ESPERADO_DEMO.items():
                x = next((y for y in f_d if str(y.get("item_id", "")).endswith(cod)), None)
                if x is None:
                    filas.append({"código": cod, "esperado": ETIQUETA[est], "obtenido": "—", "motivos": "", "¿coincide?": "no está", "caso": nota})
                    continue
                mot = ", ".join(x.get("motivos_revision") or [])
                coincide = x.get("estado") == est and (motivo is None or motivo in mot)
                filas.append({"código": cod, "esperado": ETIQUETA[est], "obtenido": ETIQUETA.get(x.get("estado"), x.get("estado")),
                              "motivos": mot or (f"SKU {x['duplicado_de']}" if x.get("duplicado_de") else ""),
                              "¿coincide?": "sí" if coincide else "NO", "caso": nota})
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
        else:
            st.markdown("**Productos del archivo cargado**")
            st.dataframe(pintar(df_fichas(f_d)), use_container_width=True, hide_index=True)

# ============================================================================= 2. Fichas
with tab_fic:
    st.subheader("Qué se puede dar de alta y qué necesita revisión")
    if not fichas:
        st.warning("Esta carpeta no tiene fichas.")
    else:
        metricas_estados(fichas)
        df = df_fichas(fichas)
        c1, c2 = st.columns([1, 2])
        provs = sorted({i.split(":")[0] for i in df["item"]})
        sel_p = c1.multiselect("Proveedor", provs, default=provs, format_func=nom)
        sel_e = c2.multiselect("Estado", list(ETIQUETA), default=list(ETIQUETA), format_func=lambda e: ETIQUETA[e])
        vista = df[df["item"].str.split(":").str[0].isin(sel_p) & df["estado"].isin(sel_e)]
        st.dataframe(pintar(vista), use_container_width=True, hide_index=True, height=300)
        st.caption("Verde: lista para alta · Gris: duplicado (con su SKU) · Coral: a revisión (con su motivo).")

        st.divider()
        st.subheader("Cada dato, con su origen")
        ids = list(vista["item"]) or list(df["item"])
        item = st.selectbox("Producto", ids)
        x = next(y for y in fichas if y.get("item_id") == item)
        est = x.get("estado")
        borde = {"lista_para_alta": VERDE_CLARO, "duplicado": PIEDRA, "a_revision": CORAL}.get(est, PIEDRA)
        st.markdown(f"<div class='estado-box' style='background:{COLOR.get(est, '#eee')};border-color:{borde}'>"
                    f"<b>{ETIQUETA.get(est, est)}</b>"
                    + (f" · ya existe como <b>{x['duplicado_de']}</b>" if x.get("duplicado_de") else "")
                    + (f" · motivo: <b>{', '.join(x.get('motivos_revision') or [])}</b>" if x.get("motivos_revision") else "")
                    + "</div>", unsafe_allow_html=True)
        fi, fu = x.get("ficha") or {}, x.get("fuentes") or {}
        campos = pd.DataFrame([{"campo": k, "valor": "" if v is None else str(v), "de dónde salió": fuente_txt(fu.get(k))}
                               for k, v in fi.items() if v is not None or k in fu])
        st.dataframe(campos, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Por qué quedan productos para revisar")
        motivos = pd.Series([m for y in fichas for m in (y.get("motivos_revision") or [])]).value_counts()
        if len(motivos):
            st.bar_chart(motivos)

# ============================================================================= 3. Asistente
with tab_asi:
    st.subheader("Preguntas sobre lo que se procesó")
    st.caption("Solo lectura. Los números los cuenta el código y toda fuente que cita tiene que haber salido de una tool; "
               "si no, un hook frena la respuesta.")
    datos = leer_json(RESPUESTAS, {})
    resps = [r for r in datos.get("respuestas", []) if r.get("pregunta")]  # V01/V02 son conversaciones
    orden = ["LT-3447", "AN-1124", "NV-203", "jabón Pureza"]   # el orden del guion primero
    resps = sorted(resps, key=lambda r: next((i for i, k in enumerate(orden) if k in r["pregunta"]), 99))
    if resps:
        preg = st.selectbox("Preguntas ya ensayadas", [r["pregunta"] for r in resps])
        r = next(y for y in resps if y["pregunta"] == preg)
        resp = r.get("respuesta", {})
        st.markdown(resp.get("texto", ""))
        if resp.get("abstiene"):
            st.info("El asistente dijo que no tiene el dato (no inventa).")
        if resp.get("fuentes"):
            st.markdown("**Fuentes citadas**")
            for f in resp["fuentes"]:
                st.markdown(f"- {fuente_txt(f)}")
        st.caption(f"USD {r.get('costo_usd', 0):.5f} · {r.get('segundos', '?')} s · tools: {', '.join(r.get('tools') or []) or '—'}"
                   + (f" · el hook frenó {len(r['rechazos_del_hook'])} vez/veces" if r.get("rechazos_del_hook") else ""))
    st.divider()
    st.markdown("**Hacer una pregunta nueva**")
    con_demo = st.checkbox("Incluir lo procesado en `resultados/demo`", value=True)
    q = st.text_input("Pregunta")
    if st.button("Preguntar") and q.strip():
        cmd = [sys.executable, "asistente/asistente.py", q.strip()] + (["--con-demo"] if con_demo else [])
        with st.spinner("Consultando…"):
            p = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=170)
        st.text(p.stdout.strip() or p.stderr.strip()[-1500:])

# ============================================================================= Costos
with tab_cos:
    st.subheader("Cuánto cuesta cada ficha y cuánto tarda")
    ref = leer_json(RES / "final" / "resumen_corrida.json", {})
    rt = leer_json(RES / "evidencia" / "resumen_tiempo_real.json", {})
    if not ref:
        st.warning("No encuentro la corrida completa en resultados/final.")
    else:
        inp, out, cache, _c, _f, _l = resumen_tokens_costo("final")
        a, b, c, d = st.columns(4)
        a.metric("Costo de los 9 proveedores", f"USD {ref.get('costo_usd', 0):.2f}")
        b.metric("Por ficha", f"USD {ref.get('costo_por_ficha_usd', 0):.5f}")
        c.metric("Tiempo total", f"{ref.get('segundos_total', 0) / 60:.0f} min", help="Corrida por Batch, sin intervención.")
        d.metric("Entrada desde caché", f"{cache / (inp + cache):.0%}" if (inp + cache) else "—",
                 help=f"{cache:,} tokens leídos de caché contra {inp:,} de entrada nueva (escritor).".replace(",", "."))

        st.markdown("### Batch o tiempo real")
        def _fila(nombre, r):
            fallas = sum(len(p.get("fallas") or []) for p in r.get("proveedores", []))
            return {"Modo": nombre, "Fichas": f"{r.get('fichas', 0)} de 257", "Costo": f"USD {r.get('costo_usd', 0):.2f}",
                    "Por ficha": f"USD {r.get('costo_por_ficha_usd', 0):.5f}", "Tiempo": f"{r.get('segundos_total', 0) / 60:.1f} min",
                    "Lotes con falla": fallas}
        filas = [_fila("Batch (corrida final)", ref)]
        if rt:
            filas.append(_fila("Tiempo real (corrida de comparación)", rt))
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
        st.caption("El Batch cuesta la mitad y tarda más, pero nadie espera el alta en tiempo real. La corrida en tiempo real "
                   "tuvo un lote cortado por `max_tokens` (Andes quedó incompleto), así que no es comparable ficha a ficha: "
                   "sirve para el costo y el tiempo, no para la calidad. Es una sola medición por modo.")

        st.markdown("### Costo por ficha según el proveedor")
        cpf = pd.DataFrame([{"Proveedor": nom(p["carpeta"].split("_")[0]), "USD por ficha": p["costo_usd"] / p["fichas"]}
                            for p in ref.get("proveedores", []) if p.get("fichas")]).set_index("Proveedor")
        try:
            st.bar_chart(cpf, color="#3FA06F")
        except TypeError:
            st.bar_chart(cpf)
        st.caption(f"Entre USD {cpf['USD por ficha'].min():.5f} ({cpf['USD por ficha'].idxmin()}) y USD {cpf['USD por ficha'].max():.5f} "
                   f"({cpf['USD por ficha'].idxmax()}) por ficha. Con 14 a 50 fichas por proveedor, la diferencia no alcanza para atribuirla "
                   "al tipo de archivo.")

        st.markdown("### Dónde se va el tiempo")
        seg_t, seg_e, seg_w = ref.get("segundos_total", 0), ref.get("segundos_extraccion", 0), ref.get("segundos_escritura", 0)
        a, b, c = st.columns(3)
        a.metric("Extracción (en paralelo)", f"{seg_e:.0f} s")
        b.metric("Escritura (un solo escritor)", f"{seg_w:.0f} s")
        c.metric("Parte del total en la escritura", f"{seg_w / seg_t:.0%}" if seg_t else "—")
        st.markdown("Los extractores corren en paralelo y la escritura va en lotes de a uno: es el cuello de botella. "
                    "En la comparación de 3 proveedores en tiempo real, **paralelo 356 s contra secuencial 819 s** (2,3 veces); "
                    "en Rivera la escritura fue 316 de esos 356 s. Acelerar solo la extracción mueve poco el total (medición del README).")

        st.markdown("### Contra hacerlo a mano")
        c1, c2 = st.columns(2)
        min_manual = c1.number_input("Minutos por ficha a mano (supuesto: cambialo)", min_value=0.5, value=3.0, step=0.5)
        costo_hora = c2.number_input("Costo de una hora de trabajo, USD (supuesto: cambialo)", min_value=0.0, value=5.0, step=1.0)
        tot = ref.get("fichas", 0)
        horas_manual = tot * min_manual / 60
        a, b, c = st.columns(3)
        a.metric("A mano (supuesto)", f"{horas_manual:.1f} h", help=f"{tot} fichas × {min_manual:g} min")
        b.metric("A mano en dinero (supuesto)", f"USD {horas_manual * costo_hora:.0f}")
        c.metric("Con el sistema", f"USD {ref.get('costo_usd', 0):.2f}", help="Más la revisión de la cola y la auditoría, que no incluye.")
        st.caption("El costo del sistema no incluye la lectura de PDF que hace el servidor con su propio llamado, ni la revisión humana "
                   "de la cola, ni la auditoría. Los dos supuestos de arriba son de ejemplo: reemplazalos con los de Compras.")

        asis = leer_json(RESPUESTAS, {})
        if asis.get("costo_total_usd"):
            st.markdown("### El asistente")
            st.markdown(f"Las {len(asis.get('respuestas', []))} consultas ensayadas costaron **USD {asis['costo_total_usd']:.4f}** en total "
                        f"({asis.get('modelo', '')}); una pregunta cuesta entre USD 0,0004 y 0,004 según cuánto tenga que buscar.")

# ============================================================================= Proveedores
with tab_prov:
    st.subheader("Qué le falla a cada proveedor")
    st.caption("Sobre la corrida completa de 9 proveedores (`resultados/final`). Un producto a revisión es un problema en los datos "
               "que mandó el proveedor; ver abajo qué se puede y qué no se puede afirmar.")
    fin = cargar_fichas("final", mtime("final")) if (RES / "final").exists() else []
    if not fin:
        st.warning("No encuentro la corrida completa en resultados/final.")
    else:
        nombres = {}
        try:
            import csv as _csv
            with open(RAIZ / "data" / "proveedores" / "proveedores.csv", encoding="utf-8-sig", newline="") as fh:
                for fila in _csv.DictReader(fh):
                    nombres[fila["proveedor_id"]] = fila
        except Exception:
            pass
        nom = lambda p: (nombres.get(p, {}).get("nombre") or p)

        @st.cache_data(show_spinner=False)
        def _analisis(_mt: float):
            return CAL.analisis(fin)
        A = _analisis(mtime("final"))
        provs, n, k, por_tipo = A["provs"], A["n"], A["k"], A["por_tipo"]
        tipos_vis = [t for t in CAL.TIPOS if t != "posible_duplicado"]

        filas = []
        for i, pv in enumerate(provs):
            lo, hi = CAL.wilson(int(k[i]), int(n[i]))
            dom = [CAL.NOMBRE_TIPO[t] for t in tipos_vis if por_tipo[i, CAL.TIPOS.index(t)] > 0]
            fila = {"Proveedor": nom(pv), "Productos": int(n[i]), "A revisión": int(k[i]),
                    "Tasa": f"{k[i] / n[i]:.0%}", "Intervalo 95 %": f"{lo:.0%} a {hi:.0%}"}
            for t in tipos_vis:
                fila[CAL.NOMBRE_TIPO[t]] = int(por_tipo[i, CAL.TIPOS.index(t)])
            fila["Perfil"] = " + ".join(dom) if dom else "Sin problemas"
            filas.append(fila)
        dfp = pd.DataFrame(filas)
        cols_tipo = [CAL.NOMBRE_TIPO[t] for t in tipos_vis]
        st.dataframe(dfp.style.background_gradient(subset=cols_tipo, cmap=_cmap_coral(), vmin=0, vmax=max(1, int(por_tipo.max()) + 1)),
                     use_container_width=True, hide_index=True)
        tot_k, tot_n = int(k.sum()), int(n.sum())
        lo, hi = CAL.wilson(tot_k, tot_n)
        st.markdown(f"En total, **{tot_k} de {tot_n}** productos ({tot_k / tot_n:.1%}) quedaron a revisión "
                    f"(intervalo de Wilson 95 %: {lo:.1%} a {hi:.1%}).")

        st.markdown("### ¿Hay proveedores peores que otros?")
        ph = A["p_tipos_holm"]
        st.info(
            f"**Considerando todos los problemas juntos, no.** Las diferencias entre proveedores en la tasa de revisión son "
            f"compatibles con el azar (p = {A['p_global']:.2f}): con 257 productos y 9 proveedores, un ranking de quién falla más "
            f"no se sostiene.\n\n"
            f"**Por tipo de problema sí hay patrón.** Los datos obligatorios faltantes se concentran en pocos proveedores "
            f"(p ajustado = {ph['dato_obligatorio_faltante']:.3f}). La falta de EAN y los conflictos entre archivos también "
            f"se concentran, pero con la corrección por probar varios tipos a la vez quedan en el límite "
            f"(p ajustado = {ph['gtin_faltante']:.2f} y {ph['conflicto_entre_fuentes']:.2f}).\n\n"
            f"**Lo útil para Compras:** no priorizar por proveedor sino por tipo de problema. Un pedido de EAN resuelve la mayor parte "
            f"de la cola; los datos obligatorios y los conflictos entre archivos son pedidos distintos a proveedores distintos.")

        with st.expander("Detalle estadístico"):
            tp = pd.DataFrame([{"Tipo de problema": CAL.NOMBRE_TIPO[t], "Casos": int(por_tipo[:, CAL.TIPOS.index(t)].sum()),
                                "p (permutación)": round(A["p_tipos"][t], 4), "p ajustado (Holm)": round(A["p_tipos_holm"][t], 4)}
                               for t in CAL.TIPOS])
            st.dataframe(tp, use_container_width=True, hide_index=True)
            st.markdown("**Cómo se calculó.** Chi-cuadrado de homogeneidad entre proveedores, con el p por permutación de 10.000 "
                        "reordenamientos al azar (hay celdas con pocos casos y el chi-cuadrado clásico no es confiable). "
                        "Se prueban 5 tipos a la vez, así que se corrige con Holm. Semilla fija: el resultado es el mismo en cada corrida.")
            est = pd.DataFrame({"Proveedor": [nom(pv) for pv in provs], "Tasa observada": [f"{k[i] / n[i]:.1%}" for i in range(len(provs))],
                                "Tasa con contracción": [f"{A['post_media'][i]:.1%}" for i in range(len(provs))],
                                "Intervalo 90 %": [f"{A['post_ic'][i][0]:.1%} a {A['post_ic'][i][1]:.1%}" for i in range(len(provs))],
                                "Prob. de ser el de más problemas": [f"{A['p_peor'][i]:.0%}" for i in range(len(provs))]})
            st.dataframe(est, use_container_width=True, hide_index=True)
            st.markdown(f"**Contracción.** Estimación beta-binomial de Bayes empírico (tasa media {A['mu_prior']:.0%}, "
                        f"concentración {A['kappa_prior']:.0f}): acerca la tasa de los proveedores con pocos productos a la del conjunto, "
                        f"para no sacar conclusiones de 14 o 18 casos. Que ningún proveedor supere el {A['p_peor'].max():.0%} de "
                        f"probabilidad de ser el peor es otra forma de ver que no hay uno que se destaque.")

        st.markdown("### Pedido listo para cada proveedor")
        pv_sel = st.selectbox("Proveedor", provs, format_func=nom, key="pv_pedido")
        info = nombres.get(pv_sel, {})
        txt = CAL.mensaje_proveedor(nom(pv_sel), " y ".join(a for a in info.get("archivos", "").split(" | ") if a and "fichas_de_seguridad" not in a) or "el archivo enviado",
                                    [x for x in fin if CAL.proveedor_de(x["item_id"]) == pv_sel])
        st.caption("Borrador armado por código a partir de los motivos (no lo redacta el modelo). Revisalo antes de enviarlo.")
        st.code(txt, language="text")
        st.download_button("Descargar borrador", txt, file_name=f"pedido_{pv_sel}.txt")

        st.markdown("### Qué hay que tener en cuenta")
        st.markdown("- **La cola mide lo que el sistema detectó**, no la calidad real del archivo: un dato malo que pasó sin frenar no figura acá.\n"
                    "- Los proveedores se usaron para ajustar el sistema (menos Dermalab, y su segunda corrida no es una prueba limpia), así que "
                    "parte del perfil de cada uno refleja decisiones de diseño y no solo sus datos.\n"
                    "- Los motivos no son independientes (la falta de EAN arrastra el posible duplicado), por eso el posible duplicado no se cuenta aparte.\n"
                    "- Con más proveedores o más cargas, el ranking podría empezar a sostenerse; hoy el tamaño de muestra no alcanza.")

# ============================================================================= 4. Confianza
with tab_conf:
    st.subheader("Cuánto se puede confiar, y cómo controlarlo")
    st.markdown("No se muestra un 100 %: se muestra cuánto se puede afirmar con una muestra chica, y cómo controlar el resto.")

    st.markdown("### Acierto contra fichas verificadas a mano")
    filas = []
    for nombre, (k, n) in {"Ficha entera": EVAL_FICHA, "Fuente de cada campo": EVAL_FUENTE}.items():
        lo, hi = wilson(k, n)
        filas.append({"métrica": nombre, "aciertos": f"{k}/{n}", "observado": f"{k / n:.0%}",
                      "Wilson 95 %": f"{lo:.0%} a {hi:.0%}"})
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.caption("15 productos verificados a mano en 2 proveedores (Andes 7, Litoral 8). Los 3 errores de fuente son del mismo tipo "
               "en Andes: el código del proveedor quedó atribuido a la actualización de precios (Excel) y no a la lista PDF "
               "esperada. Son las mismas fichas con las que se ajustó el sistema: no mide generalización. "
               "Solo hubo 2 corridas completas por modo, no 5, así que la estabilidad no se afirma con un intervalo.")

    st.markdown("### Plan de muestreo para Compras")
    ref = leer_json(RES / "final" / "resumen_corrida.json", {})
    listas = sum(p["estados"]["lista_para_alta"] for p in ref.get("proveedores", []))
    N = st.number_input("Fichas listas para alta (N)", min_value=1, value=int(listas or 208), step=1)
    tasa = st.select_slider("Error máximo tolerable", options=[0.01, 0.02, 0.03, 0.05, 0.10], value=0.05,
                            format_func=lambda v: f"{v:.0%}")
    n = n_auditoria(int(N), tasa)
    st.success(f"De **{int(N)}** fichas listas para alta, Compras audita **{n}** elegidas al azar. "
               f"Si no encuentra ningún error, puede afirmar con 95 % de confianza que el error del lote es menor al {tasa:.0%}. "
               f"Si encuentra alguno, se audita todo el lote.")
    st.caption("Muestreo sin reposición de lote finito (hipergeométrica), tolerancia cero en la muestra. "
               "Se aplica a las fichas que el sistema dejó sin revisión humana.")

    st.markdown("### Dermalab: el proveedor apartado")
    diag = RAIZ / "resultados" / "evidencia" / "diagnostico_dermalab.md"
    st.warning("Se corrió una vez con el sistema como estaba y los nombres de los productos salieron corridos un bloque: "
               "el PDF trae una ficha por producto con el nombre arriba del código. Los hooks revisan la forma, no si el "
               "dato corresponde. Se arregló después, y la segunda corrida **no es una prueba limpia**.")
    if diag.exists():
        with st.expander("Diagnóstico producto por producto"):
            st.markdown(diag.read_text(encoding="utf-8"))
    st.markdown("### Límites")
    st.markdown("- El modelo no es determinista: no corrijas en vivo un estado que salga distinto.\n"
                "- Los controles en código reducen el riesgo, no lo eliminan.\n"
                "- Los 8 proveedores restantes se usaron para ajustar el sistema.")
