import json
from datetime import date
import anthropic
import os
from dotenv import load_dotenv
load_dotenv()

client = anthropic.Anthropic()

SYSTEM_PROMPT = """Sos un agente asistente de Taligent.
## Tu rol
Ayudás a analizar problemas y proponer soluciones paso a paso.
## Reglas
- Pensá en voz alta: mostrá tu razonamiento
- Respondé siempre en español
- Sé directo y concreto
- Para contar texto (palabras, oraciones, caracteres) y formatear fechas usá solamente las tools
## Cuándo terminás
Cuando hayas completado la tarea, terminá con exactamente esta línea:
TAREA COMPLETADA: [una línea describiendo qué hiciste]
Si todavía estás trabajando, NO uses esa frase.
"""

TOOLS = [
    {
        "name": "contar_palabras",
        "description": "Cuenta palabras, oraciones y caracteres de un texto.",
        "input_schema": {
            "type": "object",
            "properties": {"texto": {"type": "string"}},
            "required": ["texto"],
        },
    },
    {
        "name": "formatear_fecha",
        "description": "Convierte una fecha ISO (2026-10-20) a 'martes 20 de octubre de 2026'.",
        "input_schema": {
            "type": "object",
            "properties": {"fecha_iso": {"type": "string"}},
            "required": ["fecha_iso"],
        },
    },
]
 
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
 
def contar_palabras(texto: str) -> dict:
    oraciones = texto.replace("!", ".").replace("?", ".").split(".")
    return {
        "palabras": len(texto.split()),
        "oraciones": len([o for o in oraciones if o.strip()]),
        "caracteres": len(texto),
    }
 
def formatear_fecha(fecha_iso: str) -> dict:
    d = date.fromisoformat(fecha_iso)
    return {"fecha": f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"}
 

def ejecutar_tool(nombre: str, argumentos: dict) -> str:
    if nombre == "contar_palabras":
        resultado = contar_palabras(**argumentos)
        return json.dumps(resultado)
    if nombre == "formatear_fecha":
        resultado = formatear_fecha(**argumentos)
        return json.dumps(resultado)
    return json.dumps({"error": f"Tool '{nombre}' no encontrada"})

def run_agent(tarea: str, max_iteraciones: int = 5) -> str:
    """
    Corre el agente en loop hasta que complete la tarea o llegue al límite.
    """
    mensajes = [{"role": "user", "content": tarea}]
    
    for iteracion in range(max_iteraciones):
        print(f"\n--- Iteración {iteracion + 1} ---")
        
        response = client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=mensajes
        )
        
        texto_respuesta = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        print(f"Agente: {texto_respuesta}")
        
        # Acumular en el historial
        mensajes.append({
            "role": "assistant",
            "content": response.content
        })
        
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [tool] {block.name}({block.input})")
                    resultado = ejecutar_tool(block.name, block.input)
                    print(f"  [resultado] {resultado}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": resultado,
                    })
            mensajes.append({"role": "user", "content": tool_results})
            continue
        
        # ¿El agente terminó?
        if "TAREA COMPLETADA:" in texto_respuesta:
            print(f"\n✅ Agente completó la tarea en {iteracion + 1} iteración/es.")
            return texto_respuesta
            
        # Si no terminó, pedirle que continúe
        mensajes.append({
            "role": "user",
            "content": "Continuá con la tarea. Si ya terminaste, usá la frase TAREA COMPLETADA."
        })
        
    return f"⚠️ El agente llegó al límite de {max_iteraciones} iteraciones sin completar la tarea."

if __name__ == "__main__":
    resultado = run_agent(
        "Contá la cantidad de palabras en este texto: 'Hoy 2026-10-18 desayuné café negro y tostadas con mermelada'. También dame la fecha estandarizada."
    )