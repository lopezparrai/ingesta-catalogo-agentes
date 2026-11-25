"""Calidad de datos por proveedor: estadística sobre la cola de revisión.

Todo es código determinista sobre las fichas ya generadas (no llama a la API). Semilla fija: mismo resultado cada vez.

Idea: un producto "a revisión" es un defecto de los datos que mandó el proveedor (todos los de la corrida final tienen
`gtin_faltante`, `gtin_invalido`, `dato_obligatorio_faltante` o `conflicto_entre_fuentes`; `posible_duplicado` es consecuencia
de no tener EAN para confirmar). Se mide:
  1. la tasa de defecto por proveedor con intervalo de Wilson;
  2. si los proveedores difieren entre sí (chi-cuadrado con p por permutación, porque hay celdas con pocos casos);
  3. lo mismo por tipo de problema, con corrección de Holm por probar varios tipos a la vez;
  4. una estimación con contracción (beta-binomial de Bayes empírico) para no sobreinterpretar proveedores chicos.
"""
import math

import numpy as np

TIPOS = ["gtin_faltante", "gtin_invalido", "dato_obligatorio_faltante", "conflicto_entre_fuentes", "posible_duplicado"]
NOMBRE_TIPO = {
    "gtin_faltante": "Falta el EAN",
    "gtin_invalido": "EAN inválido",
    "dato_obligatorio_faltante": "Datos obligatorios faltantes",
    "conflicto_entre_fuentes": "Datos que no coinciden entre archivos",
    "posible_duplicado": "Posible duplicado (sin EAN para confirmar)",
}
SEMILLA = 20261125


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def proveedor_de(item_id: str) -> str:
    return item_id.split(":")[0]


def tabla_proveedores(fichas: list[dict]):
    """Devuelve (proveedores ordenados, n por proveedor, k a revisión, matriz de conteos por tipo)."""
    provs = sorted({proveedor_de(x["item_id"]) for x in fichas})
    idx = {p: i for i, p in enumerate(provs)}
    n = np.zeros(len(provs), int)
    k = np.zeros(len(provs), int)
    por_tipo = np.zeros((len(provs), len(TIPOS)), int)
    for x in fichas:
        i = idx[proveedor_de(x["item_id"])]
        n[i] += 1
        if x.get("estado") == "a_revision":
            k[i] += 1
        for m in x.get("motivos_revision") or []:
            if m in TIPOS:
                por_tipo[i, TIPOS.index(m)] += 1
    return provs, n, k, por_tipo


def _chi2(k, n, pool):
    e = n * pool
    return (((k - e) ** 2) / (e * (1 - pool))).sum(axis=-1)


def test_homogeneidad(etiqueta_prov: np.ndarray, y: np.ndarray, n_prov: int, B: int = 10000):
    """p por permutación del chi-cuadrado de homogeneidad de una variable 0/1 entre proveedores."""
    n = np.bincount(etiqueta_prov, minlength=n_prov).astype(float)
    pool = y.mean()
    if pool in (0.0, 1.0):
        return 1.0
    k = np.bincount(etiqueta_prov, weights=y, minlength=n_prov)
    obs = _chi2(k, n, pool)
    rng = np.random.default_rng(SEMILLA)
    onehot = np.eye(n_prov)[etiqueta_prov]                       # N x P
    perm = rng.permuted(np.tile(y, (B, 1)), axis=1)              # B x N
    kk = perm @ onehot                                           # B x P
    return float(((_chi2(kk, n, pool) >= obs - 1e-12).sum() + 1) / (B + 1))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    orden = sorted(pvals, key=pvals.get)
    m = len(orden)
    ajust, previo = {}, 0.0
    for i, nombre in enumerate(orden):
        previo = max(previo, min(1.0, (m - i) * pvals[nombre]))
        ajust[nombre] = previo
    return ajust


def analisis(fichas: list[dict], B: int = 10000) -> dict:
    provs, n, k, por_tipo = tabla_proveedores(fichas)
    etiqueta = np.array([provs.index(proveedor_de(x["item_id"])) for x in fichas])
    y_rev = np.array([1.0 if x.get("estado") == "a_revision" else 0.0 for x in fichas])
    p_global = test_homogeneidad(etiqueta, y_rev, len(provs), B)
    p_tipos = {}
    for t in TIPOS:
        y = np.array([1.0 if t in (x.get("motivos_revision") or []) else 0.0 for x in fichas])
        p_tipos[t] = test_homogeneidad(etiqueta, y, len(provs), B)
    # Posterior con contracción (beta-binomial, Bayes empírico por máxima verosimilitud en una grilla)
    lg = math.lgamma

    def ll(mu, kap):
        a, b = mu * kap, (1 - mu) * kap
        return sum(lg(ni + 1) - lg(ki + 1) - lg(ni - ki + 1) + lg(ki + a) + lg(ni - ki + b) - lg(ni + a + b)
                   + lg(a + b) - lg(a) - lg(b) for ni, ki in zip(n, k))
    mejor = max((ll(mu, kap), mu, kap) for mu in np.linspace(0.02, 0.40, 77)
                for kap in np.exp(np.linspace(0, math.log(2000), 60)))
    _, mu, kap = mejor
    a, b = mu * kap, (1 - mu) * kap
    rng = np.random.default_rng(SEMILLA)
    post = rng.beta(a + k[:, None], b + (n - k)[:, None], size=(len(provs), 20000))
    return {
        "provs": provs, "n": n, "k": k, "por_tipo": por_tipo,
        "p_global": p_global, "p_tipos": p_tipos, "p_tipos_holm": holm(p_tipos),
        "post_media": post.mean(axis=1), "post_ic": np.percentile(post, [5, 95], axis=1).T,
        "p_peor": (post == post.max(axis=0)).mean(axis=1),
        "mu_prior": mu, "kappa_prior": kap,
    }


def mensaje_proveedor(nombre: str, archivos: str, fichas_prov: list[dict]) -> str:
    """Borrador del pedido al proveedor, armado por código a partir de los motivos (no lo redacta el modelo)."""
    def cod(x):
        return (x.get("ficha") or {}).get("codigo_proveedor") or x["item_id"].split(":", 1)[-1]
    grupos = {t: [] for t in TIPOS if t != "posible_duplicado"}
    for x in fichas_prov:
        if x.get("estado") != "a_revision":
            continue
        for m in x.get("motivos_revision") or []:
            if m in grupos:
                extra = f" (posible coincidencia con {x['duplicado_de']})" if m == "gtin_faltante" and x.get("duplicado_de") else ""
                grupos[m].append(cod(x) + extra)
    if not any(grupos.values()):
        return f"{nombre}: no hay productos a revisión. Nada para pedirle."
    pedidos = {
        "gtin_faltante": "Código de barras (EAN/GTIN) de estos productos. Sin él no podemos confirmar si ya están en nuestro catálogo:",
        "gtin_invalido": "Revisar el código de barras de estos productos: el dígito verificador no es válido:",
        "dato_obligatorio_faltante": "Completar datos obligatorios que faltan en estos productos:",
        "conflicto_entre_fuentes": "Confirmar cuál de sus archivos rige: los datos de estos productos no coinciden entre sí:",
    }
    lineas = [f"Hola, {nombre}:", "",
              f"Al cargar su archivo ({archivos}) quedaron productos que no pudimos dar de alta. Para cerrarlos necesitamos:", ""]
    for t, texto in pedidos.items():
        if grupos[t]:
            lineas += [f"- {texto}", "  " + ", ".join(grupos[t])]
    lineas += ["", "Con eso los damos de alta. Gracias."]
    return "\n".join(lineas)
