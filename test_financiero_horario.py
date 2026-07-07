import sys
sys.path.append('.')

from agents.finance_agent import finance_agent
from langchain_core.messages import HumanMessage, AIMessage
import asyncio

async def main():
    messages = [
        HumanMessage(content="alumno 60741079, anghelo alexander pintado valverde, apoderado 40827747, y si ese es mi telefono"),
        AIMessage(content="""## 🎉 ¡Inscripción Registrada con Éxito!

**Alumno:** Anghelo Alexander Pintado Valverde
**Ciclo:** Intensivo 5to Secundaria (G-SEC5-2026-B)
**Monto:** S/ 750
**Estado:** Registrado

---
📌 **Importante:** Una vez realizado el pago, por favor envíeme:
- El **correo electrónico** con el que pagó en Stripe"""),
        HumanMessage(content="anghelopintadovalverde@gmail.com")
    ]
    
    # Invocamos al agente financiero
    response = await finance_agent.ainvoke({"messages": messages})
    
    for msg in response["messages"]:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            print(f"[{msg.type.upper()}] Llamó a herramientas: {', '.join([t['name'] for t in msg.tool_calls])}")
        elif msg.content:
            print(f"[{msg.type.upper()}] {msg.content[:200]}...")
            
if __name__ == "__main__":
    asyncio.run(main())
