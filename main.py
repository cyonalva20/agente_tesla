from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uuid

from orchestrator import Orchestrator

app = FastAPI(title="Academia Tesla - Sistema Multiagente")

# Almacena sesiones activas en memoria
sesiones: dict = {}


class MensajeRequest(BaseModel):
    session_id: str | None = None
    mensaje: str


class MensajeResponse(BaseModel):
    session_id: str
    respuesta: str
    fase: str
    session_data: dict


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.post("/chat", response_model=MensajeResponse)
async def chat(request: MensajeRequest):
    if request.session_id and request.session_id in sesiones:
        session_id = request.session_id
        orchestrator = sesiones[session_id]
    else:
        orchestrator = Orchestrator()
        session_id = orchestrator.session_data["session_id"]
        sesiones[session_id] = orchestrator

    try:
        respuesta = await orchestrator.procesar_mensaje(request.mensaje)
        return MensajeResponse(
            session_id=session_id,
            respuesta=respuesta,
            fase=orchestrator.session_data["fase"],
            session_data=orchestrator.session_data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/sesion/{session_id}")
async def obtener_sesion(session_id: str):
    if session_id not in sesiones:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    orch = sesiones[session_id]
    return {
        "session_id": session_id,
        "session_data": orch.session_data,
        "historial_length": len(orch.historial)
    }


@app.delete("/sesion/{session_id}")
async def limpiar_sesion(session_id: str):
    if session_id in sesiones:
        del sesiones[session_id]
        return {"mensaje": "Sesion eliminada", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Sesion no encontrada")


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
