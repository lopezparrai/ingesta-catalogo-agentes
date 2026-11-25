# Ingesta de catálogo — Taligent AI Spring Camp

Proyecto final del curso de agentes: convierte las listas de productos nuevos de los proveedores de
Farmacias Ceibo (cadena ficticia) en fichas que cumplen el estándar, detecta duplicados contra el catálogo
y manda a revisión lo que no puede resolver. Cada campo guarda de qué archivo, página, hoja/fila o línea salió.

Todo corre con la API de Anthropic y Claude Haiku 5.5 (`claude-haiku-5-5`).

## Archivos

| Archivo | Qué hace |
|---|---|
| `mi_servidor.py` | Servidor MCP (FastMCP): lee estándar, archivos de proveedores y catálogo; valida GTIN. |
| `agente.py` | Loop del agente con Claude: procesa un proveedor y registra las fichas. |
| `prompt_v2.py` | Prompt de sistema v2 (M6). |
| `salida_estructurada.py` | Clasificación con salida estructurada y validación con pydantic (M6). |
| `evaluador.py` | Compara `salidas/*.json` contra fichas verificadas a mano en `evals/`. |
| `evals/` | Casos esperados verificados a mano (Litoral, Andes). |
| `salidas/` | Salidas generadas por el agente. |

## Cómo correrlo

```bash
pip install -r requirements.txt
cp .env.example .env        # y completar ANTHROPIC_API_KEY
```

Copiar el material del curso en `data/` (`catalogo/`, `consultas/`, `estandar/`, `proveedores/`); no está
en el repo.

```bash
python agente.py P03_Distribuidora_Litoral    # procesar un proveedor
python evaluador.py                           # evaluar contra evals/
```

## Estado

- M1–M3: funcionando sobre Litoral y Laboratorio Andes (ver `evals/`).
- M6: prompt v2 y salida estructurada.
- Pendiente: M4 (multi-agente en paralelo), M5 (hooks y permisos), integración de los 9 proveedores con un
  comando y asistente de consultas.

<!-- TODO: documentar las decisiones de diseño con su porqué -->
