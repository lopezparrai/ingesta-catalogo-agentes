"""Scorecard de calidad por proveedor: estimación con contracción (beta-binomial, Bayes empírico).

Es código determinista sobre las fichas ya generadas (no llama a la API). Semilla fija: mismo resultado cada vez.

Idea: un producto "a revisión" es un defecto de los datos que mandó el proveedor. Con pocos productos, el
porcentaje crudo de un proveedor engaña; por eso se estima la tasa de defecto de cada uno contrayéndola hacia
la tasa general, tanto más cuanto menos productos tiene (beta-binomial, con los parámetros del prior estimados
por máxima verosimilitud en una grilla). La app muestra la tasa cruda, la ajustada, su intervalo de credibilidad
y la probabilidad de ser el proveedor con peor calidad.
"""
import math

import numpy as np

SEMILLA = 20261125
SIMULACIONES = 20000


def proveedor_de(item_id: str) -> str:
    return item_id.split(":")[0]


def analisis(fichas: list[dict]) -> dict:
    """Devuelve, por proveedor (ordenados por id): n productos, k a revisión y la tasa ajustada con su intervalo."""
    provs = sorted({proveedor_de(x["item_id"]) for x in fichas})
    idx = {p: i for i, p in enumerate(provs)}
    n = np.zeros(len(provs), int)
    k = np.zeros(len(provs), int)
    for x in fichas:
        i = idx[proveedor_de(x["item_id"])]
        n[i] += 1
        if x.get("estado") == "a_revision":
            k[i] += 1

    lg = math.lgamma

    def log_verosimilitud(mu, kap):
        a, b = mu * kap, (1 - mu) * kap
        return sum(lg(ni + 1) - lg(ki + 1) - lg(ni - ki + 1) + lg(ki + a) + lg(ni - ki + b) - lg(ni + a + b)
                   + lg(a + b) - lg(a) - lg(b) for ni, ki in zip(n, k))

    _, mu, kap = max((log_verosimilitud(mu, kap), mu, kap) for mu in np.linspace(0.02, 0.40, 77)
                     for kap in np.exp(np.linspace(0, math.log(2000), 60)))
    a, b = mu * kap, (1 - mu) * kap
    rng = np.random.default_rng(SEMILLA)
    post = rng.beta(a + k[:, None], b + (n - k)[:, None], size=(len(provs), SIMULACIONES))
    return {
        "provs": provs, "n": n, "k": k,
        "post_media": post.mean(axis=1), "post_ic": np.percentile(post, [2.5, 97.5], axis=1).T,
        "p_peor": (post == post.max(axis=0)).mean(axis=1),
        "mu_prior": mu, "kappa_prior": kap,
    }
