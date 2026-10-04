import os
import json
from dotenv import load_dotenv

load_dotenv()



from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional
from llm_engine import stream_chat

app = FastAPI(title="TNEA GPT", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "assets")), name="assets")

# ── Maximum allowed history length (messages) to prevent context overflow ──
MAX_HISTORY_LENGTH = 40
MAX_MESSAGE_LENGTH = 2000

class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty.")
        if len(v) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message exceeds maximum length of {MAX_MESSAGE_LENGTH} characters.")
        return v

    @field_validator("history")
    @classmethod
    def validate_history(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        clean: List[Dict[str, Any]] = []
        for msg in v:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                clean.append({"role": role, "content": content[:MAX_MESSAGE_LENGTH]})
        # Keep only the most recent messages to stay within context limits
        return clean[-MAX_HISTORY_LENGTH:]

@app.get("/")
async def serve_ui():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/health")
async def health_check():
    """Production-friendly health check without exposing secrets."""
    from llm_engine import client as llm_client, MODEL_NAME
    return {"status":"ok","service":"tnea-gpt","ai_configured":llm_client is not None,"model":MODEL_NAME if llm_client is not None else None}

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        return StreamingResponse(
            stream_chat(req.message.strip(), req.history),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Chat service error: {str(e)}"}
        )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "An unexpected error occurred. Please try again."}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)