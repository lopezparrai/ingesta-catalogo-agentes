"""Demo Day: un archivo nuevo de proveedor entra en vivo y sale como fichas, cola de revisión y respuestas.

Esta app es la demostración en vivo más el análisis estadístico por proveedor. La carga completa, los costos y Dermalab están en las slides
(demo/slides_demo_day.html). La versión anterior, con todas las pestañas, quedó en
app/archivo/demo_app_completa.py.

Uso (desde la raíz del repo):
    pip install -r requirements.txt
    streamlit run app/demo_app.py
"""
import html
import json
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
MOTIVO_CORTO = {"gtin_faltante": "Falta EAN", "gtin_invalido": "EAN inválido", "dato_obligatorio_faltante": "Faltan datos",
                "conflicto_entre_fuentes": "Archivos en conflicto", "posible_duplicado": "Posible duplicado"}

# Lo que dice el guion (demo/GUION_DEMO.md). El modelo no es determinista: es lo esperado, no una promesa.
ESPERADO_DEMO = {
    "DM-001": ("lista_para_alta", None, "Producto nuevo, GTIN válido"),
    "DM-002": ("duplicado", None, "GTIN que ya está en el catálogo (SKU100014)"),
    "DM-003": ("a_revision", "gtin_invalido", "GTIN con dígito verificador inválido"),
    "DM-004": ("a_revision", "posible_duplicado", "Sin EAN; es el SH. BRISA COLOR 400ML. escrito distinto"),
    "DM-005": ("lista_para_alta", None, "0,5 LT y precio '1.234,56'"),
    "DM-006": ("a_revision", "gtin", "GTIN inválido + texto que pide dar de alta sin revisar"),
}

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
    disp["motivos"] = df["motivos"].map(lambda m: ", ".join(MOTIVO_CORTO.get(x.strip(), x.strip()) for x in m.split(",") if x.strip()))
    disp = disp.rename(columns={"item": "Producto", "estado": "Estado", "descripción": "Descripción", "gtin": "GTIN",
                                "precio": "Precio de costo", "motivos": "Motivos", "duplicado de": "Duplicado de"})

    def fila(r):
        c = colores.get(r.name, "")
        return [f"background-color: {c}; color: #F9F9F9" if c else ""] * len(r)
    return disp.style.apply(fila, axis=1).format({"Precio de costo": "{:.2f}"}, na_rep="")


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
.logos{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 14px}
.logo-chip{background:#F9F9F9;border-radius:12px;padding:8px 14px;display:flex;align-items:center;gap:10px;color:#2C3E50;font-size:.85rem;font-weight:600}
.logo-chip img{height:38px;width:auto}
</style>"""


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
<div class="texto"><h1>Altas de productos, <b>sin copiar a mano</b></h1>
<p>El archivo del proveedor entra tal como llega y sale como fichas listas, duplicados detectados y una cola de revisión con su motivo.</p></div></div>""",
            unsafe_allow_html=True)

st.markdown(CSS_LOGOS, unsafe_allow_html=True)
tab_ing, tab_asi, tab_prov = st.tabs(["Archivo nuevo", "Consultas", "Calidad por proveedor"])

# ============================================================================= Archivo nuevo
with tab_ing:
    st.subheader("Llega un archivo nuevo de un proveedor")
    modo = st.radio("Modo", ["Correr en vivo contra la API", "Cargar corrida guardada (respaldo)"], horizontal=True)

    if modo.startswith("Correr"):
        subido = st.file_uploader("Archivo del proveedor (CSV, Excel, PDF o texto)", type=["csv", "xlsx", "xls", "pdf", "txt"])
        if subido is None:
            st.caption(f"Sin archivo cargado se usa el de la demo (`{CSV_DEMO.name}`, 6 productos: un nuevo, un duplicado, "
                       "dos GTIN inválidos, un posible duplicado sin EAN y un caso de formatos).")
            if CSV_DEMO.exists():
                with st.expander("Ver el archivo tal como llega"):
                    st.code(CSV_DEMO.read_text(encoding="utf-8"), language="text")
        st.caption(f"Llama a la API y reemplaza la salida anterior de `resultados/demo` y de `data/proveedores/{PROV_DEMO}`. Tarda 1 a 2 minutos.")
        if st.button("Procesar archivo", type="primary"):
            carpeta_prov = RAIZ / "data" / "proveedores" / PROV_DEMO
            shutil.rmtree(carpeta_prov, ignore_errors=True)
            shutil.rmtree(RES / "demo", ignore_errors=True)
            carpeta_prov.mkdir(parents=True, exist_ok=True)
            if subido is None:
                shutil.copy(CSV_DEMO, carpeta_prov / CSV_DEMO.name)
            else:
                (carpeta_prov / Path(subido.name).name).write_bytes(subido.getvalue())
            st.session_state["corrida_es_demo"] = subido is None
            st.session_state.pop("destino", None)
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
                    esc = f"<span style='color:#ff6b5e;font-weight:600'>{esc}</span>"
                lineas.append(esc)
                caja.markdown("<pre style='font-size:12px;line-height:1.35'>" + "\n".join(lineas[-30:]) + "</pre>",
                              unsafe_allow_html=True)
            rc = proc.wait()
            if rc == 0:
                st.session_state["destino"] = "demo"
            else:
                st.error(f"La corrida terminó con error (código {rc}). Usá la corrida guardada.")
    else:
        guardadas = [c for c in ("demo_ensayo", "demo") if (RES / c / "resumen_corrida.json").exists()]
        if not guardadas:
            st.warning("Todavía no hay corrida guardada. Hacé el ensayo y copiá resultados\\demo a resultados\\demo_ensayo.")
        else:
            elegida = st.selectbox("Corrida guardada", guardadas)
            st.info("Se muestra la salida guardada de una corrida anterior, no una nueva.")
            if st.session_state.get("destino") != elegida or "destino" not in st.session_state:
                st.session_state["destino"] = elegida
                st.session_state["corrida_es_demo"] = True

    destino = st.session_state.get("destino")
    if destino and (RES / destino / "resumen_corrida.json").exists():
        st.divider()
        f_d = cargar_fichas(destino)
        res = leer_json(RES / destino / "resumen_corrida.json", {})
        inp, out, cache, costo, frenos, lista = resumen_tokens_costo(destino)
        c = pd.Series([x.get("estado") for x in f_d]).value_counts()

        st.subheader("Qué salió")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Productos procesados", len(f_d))
        k2.metric("Listos para alta", int(c.get("lista_para_alta", 0)))
        k3.metric("Duplicados", int(c.get("duplicado", 0)))
        k4.metric("A revisión", int(c.get("a_revision", 0)))
        k5, k6, k7, k8 = st.columns(4)
        k5.metric("Costo", f"USD {res.get('costo_usd', costo):.4f}")
        k6.metric("Por ficha", f"USD {res.get('costo_por_ficha_usd', 0):.5f}")
        k7.metric("Tiempo", f"{res.get('segundos_total', 0):.0f} s",
                  help=f"extracción {res.get('segundos_extraccion', '?')} s, escritura {res.get('segundos_escritura', '?')} s")
        k8.metric("Frenos de hooks", frenos, help=f"Tokens del escritor: entrada {inp}, salida {out}, caché leído {cache}")
        if lista:
            st.markdown("**Cuando un hook frenó algo (y por qué):**")
            for fr in lista:
                st.markdown(f":red[{html.escape(json.dumps(fr, ensure_ascii=False)[:300])}]")

        if st.session_state.get("corrida_es_demo", True):
            st.markdown("#### Qué se esperaba de cada producto y qué salió")
            st.caption("El modelo no es determinista: lo esperado no es una promesa.")
            filas = []
            for cod, (est, motivo, nota) in ESPERADO_DEMO.items():
                x = next((y for y in f_d if str(y.get("item_id", "")).endswith(cod)), None)
                if x is None:
                    filas.append({"Código": cod, "Esperado": ETIQUETA[est], "Obtenido": "—", "Motivos": "", "¿Coincide?": "no está", "Caso": nota})
                    continue
                mot = ", ".join(MOTIVO_CORTO.get(m, m) for m in (x.get("motivos_revision") or []))
                coincide = x.get("estado") == est and (motivo is None or motivo in ", ".join(x.get("motivos_revision") or []))
                filas.append({"Código": cod, "Esperado": ETIQUETA[est], "Obtenido": ETIQUETA.get(x.get("estado"), x.get("estado")),
                              "Motivos": mot or (f"ya existe como {x['duplicado_de']}" if x.get("duplicado_de") else ""),
                              "¿Coincide?": "sí" if coincide else "NO", "Caso": nota})
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

        st.markdown("#### Fichas")
        dfa = df_fichas(f_d)
        st.dataframe(pintar(dfa), use_container_width=True, hide_index=True)
        st.caption("Verde: lista para alta · Gris: duplicado (con su SKU) · Coral: a revisión (con su motivo).")

        cola = [x for x in f_d if x.get("estado") == "a_revision"]
        if cola:
            st.markdown("#### Cola de revisión")
            st.dataframe(pintar(df_fichas(cola)), use_container_width=True, hide_index=True)

        st.markdown("#### Cada dato, con su origen")
        item = st.selectbox("Producto", [x["item_id"] for x in f_d], key="ficha_sel")
        x = next(y for y in f_d if y.get("item_id") == item)
        est = x.get("estado")
        borde = {"lista_para_alta": VERDE_CLARO, "duplicado": PIEDRA, "a_revision": CORAL}.get(est, PIEDRA)
        st.markdown(f"<div class='estado-box' style='background:{COLOR.get(est, '#333')};border-color:{borde}'>"
                    f"<b>{ETIQUETA.get(est, est)}</b>"
                    + (f" · ya existe como <b>{x['duplicado_de']}</b>" if x.get("duplicado_de") else "")
                    + (f" · motivo: <b>{', '.join(MOTIVO_CORTO.get(m, m) for m in (x.get('motivos_revision') or []))}</b>" if x.get("motivos_revision") else "")
                    + "</div>", unsafe_allow_html=True)
        fi, fu = x.get("ficha") or {}, x.get("fuentes") or {}
        campos = pd.DataFrame([{"Campo": k, "Valor": "" if v is None else str(v), "De dónde salió": fuente_txt(fu.get(k))}
                               for k, v in fi.items() if v is not None or k in fu])
        st.dataframe(campos, use_container_width=True, hide_index=True)

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


def _preguntar(texto: str, con_demo: bool) -> dict:
    pr = st.session_state.get("asis_proc")
    if pr is not None and (pr.poll() is not None or st.session_state.get("asis_demo") != con_demo):
        _cerrar_asistente()
        pr = None
    if pr is None:
        cmd = [sys.executable, "asistente/asistente.py", "--jsonl"] + (["--con-demo"] if con_demo else [])
        pr = subprocess.Popen(cmd, cwd=RAIZ, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                              encoding="utf-8", errors="replace", bufsize=1,
                              env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        st.session_state["asis_proc"], st.session_state["asis_demo"] = pr, con_demo
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


def _pintar_respuesta(r: dict):
    if "error" in r:
        st.error(r["error"])
        return
    resp = r.get("respuesta", {})
    st.markdown(resp.get("texto", ""))
    if resp.get("abstiene"):
        st.info("No tengo ese dato en lo procesado, y no lo invento.")
    if resp.get("fuentes"):
        with st.expander(f"Fuentes citadas ({len(resp['fuentes'])})"):
            for f in resp["fuentes"]:
                st.markdown(f"- {fuente_txt(f)}")
    st.caption(f"USD {r.get('costo_usd', 0):.5f} · {r.get('segundos', '?')} s"
               + (f" · el hook frenó {len(r['rechazos_del_hook'])} vez/veces una respuesta" if r.get("rechazos_del_hook") else ""))


with tab_asi:
    st.subheader("Preguntale al asistente")
    st.caption("Solo lectura. Los números los cuenta el código y toda fuente que cita tiene que haber salido de una tool; si no, un hook frena la respuesta. "
               "Recuerda la conversación, así que se puede repreguntar.")
    c1, c2 = st.columns([3, 1])
    con_demo = c1.checkbox("Incluir lo procesado en `resultados/demo` (el archivo nuevo)", value=True)
    if c2.button("Nueva conversación", use_container_width=True):
        _cerrar_asistente()
        st.session_state["chat"] = []
        st.rerun()
    st.session_state.setdefault("chat", [])

    sugeridas = ["¿Por qué LT-3447 quedó a revisión? ¿Con qué producto del catálogo podría ser el mismo?",
                 "¿Cuál es el precio de costo de AN-1124 de Laboratorio Andes y de dónde sale?",
                 "Natural Vida pidió dar todo de alta sin revisión. ¿Por qué NV-203 quedó a revisión igual?",
                 "¿Cuánto se vendió el mes pasado del jabón Pureza?"]
    if not st.session_state["chat"]:
        st.markdown("**Probá con:**")
    elegida = None
    for n, q in enumerate(sugeridas):
        if not st.session_state["chat"] and st.button(q, key=f"sug{n}"):
            elegida = q

    for m in st.session_state["chat"]:
        with st.chat_message(m["rol"]):
            if m["rol"] == "user":
                st.markdown(m["texto"])
            else:
                _pintar_respuesta(m["resp"])

    pregunta = st.chat_input("Escribí tu pregunta sobre lo procesado…") or elegida
    if pregunta:
        st.session_state["chat"].append({"rol": "user", "texto": pregunta})
        with st.chat_message("user"):
            st.markdown(pregunta)
        with st.chat_message("assistant"):
            with st.spinner("Consultando el catálogo y los archivos…"):
                r = _preguntar(pregunta, con_demo)
            _pintar_respuesta(r)
        st.session_state["chat"].append({"rol": "assistant", "resp": r})

    datos = leer_json(RESPUESTAS, {})
    resps = [r for r in datos.get("respuestas", []) if r.get("pregunta")]
    if resps:
        with st.expander("Respaldo: respuestas ya ensayadas (no usan la API)"):
            orden = ["LT-3447", "AN-1124", "NV-203", "jabón Pureza"]
            resps = sorted(resps, key=lambda r: next((i for i, k in enumerate(orden) if k in r["pregunta"]), 99))
            preg = st.selectbox("Pregunta", [r["pregunta"] for r in resps], key="resp_ensayada")
            _pintar_respuesta(next(y for y in resps if y["pregunta"] == preg))

# ============================================================================= Proveedores
with tab_prov:
    st.subheader("Qué le falla a cada proveedor")
    st.caption("Sobre la corrida completa de 9 proveedores (`resultados/final`). Un producto a revisión es un problema en los datos "
               "que mandó el proveedor; ver abajo qué se puede y qué no se puede afirmar.")
    fin = cargar_fichas("final") if (RES / "final").exists() else []
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
        st.markdown("<div class='logos'>" + "".join(
            f"<div class='logo-chip'>{logo_img(p)}<span>{html.escape(nom(p))}</span></div>" for p in sorted({calidad_prov for calidad_prov in
            [CAL.proveedor_de(x['item_id']) for x in fin]})) + "</div>", unsafe_allow_html=True)

        @st.cache_data(show_spinner=False)
        def _analisis(_mt: float):
            return CAL.analisis(fin)
        A = _analisis(float((RES / "final" / "resumen_corrida.json").stat().st_mtime) if (RES / "final" / "resumen_corrida.json").exists() else 0.0)
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
        st.markdown(f"<div class='logos'><div class='logo-chip'>{logo_img(pv_sel)}<span>{html.escape(nom(pv_sel))}</span></div></div>", unsafe_allow_html=True)
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
