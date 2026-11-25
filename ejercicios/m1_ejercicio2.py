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
- Respondé siempre en inglés
- Sé directo y concreto
## Cuándo terminás
Cuando hayas completado la tarea, terminá con exactamente esta línea:
TAREA COMPLETADA: [una línea describiendo qué hiciste]
Si todavía estás trabajando, NO uses esa frase.
"""

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
            messages=mensajes
        )
        
        texto_respuesta = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        print(f"Agente: {texto_respuesta}")
        
        # Acumular en el historial
        mensajes.append({
            "role": "assistant",
            "content": texto_respuesta
        })
        
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
        "Listá 5 casos de uso de agentes de IA para una consultora de tecnología "
        "como Taligent, explicando brevemente por qué cada uno genera valor."
    )