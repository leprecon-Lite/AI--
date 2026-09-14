import os
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path

load_dotenv()

app = FastAPI(title="AI Quality Agent Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://solaris-vrn.ru",
        "https://solaris-vrn.ru",
        "http://www.solaris-vrn.ru",
        "https://www.solaris-vrn.ru",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://localhost",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

GIGA_SERVICE_URL = os.getenv("GIGA_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class ExplainRequest(BaseModel):
    rule_id: str
    actual: str | float | int


# ---------- Служебные эндпоинты ----------

@app.get("/")
def hello_message():
    return {"message": "Hello World"}


# ---------- JSON API ----------

@app.post("/upload_file/")
async def upload_file(file: UploadFile = File(...)):
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            file_content = await file.read()
            files = {"file": (file.filename, file_content, file.content_type)}

            response = await client.post(
                f"{GIGA_SERVICE_URL}/check/",
                files=files,
            )
            response.raise_for_status()
            return response.json()

        except httpx.RequestError as e:
            return {"error": f"Ошибка соединения: {str(e)}"}
        except httpx.HTTPStatusError as e:
            return {"error": f"Ошибка {e.response.status_code}: {e.response.text}"}


@app.get("/history/")
async def proxy_history(limit: int = 20):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{GIGA_SERVICE_URL}/history/", params={"limit": limit})
        return r.json()


@app.get("/history/{protocol_id}")
async def proxy_history_item(protocol_id: int):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{GIGA_SERVICE_URL}/history/{protocol_id}")
        return r.json()


@app.post("/explain/")
async def proxy_explain(req: ExplainRequest):
    """Проксирует запрос RAG-объяснения на AI-сервис."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            r = await client.post(
                f"{GIGA_SERVICE_URL}/explain/",
                json={"rule_id": req.rule_id, "actual": req.actual},
            )
            r.raise_for_status()
            return r.json()
        except httpx.RequestError as e:
            return {"error": f"Ошибка соединения: {e}"}
        except httpx.HTTPStatusError as e:
            return {"error": f"Ошибка {e.response.status_code}: {e.response.text}"}


# ---------- HTML API для htmx ----------

@app.post("/ui/check/", response_class=HTMLResponse)
async def ui_check(request: Request, file: UploadFile = File(...)):
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            content = await file.read()
            files = {"file": (file.filename, content, file.content_type)}
            r = await client.post(f"{GIGA_SERVICE_URL}/check/", files=files)
            r.raise_for_status()
            data = r.json()
        except httpx.RequestError as e:
            return templates.TemplateResponse(
                request=request,
                name="result_error.html",
                context={"error": f"Ошибка соединения: {e}"},
            )
        except httpx.HTTPStatusError as e:
            return templates.TemplateResponse(
                request=request,
                name="result_error.html",
                context={"error": f"Ошибка {e.response.status_code}"},
            )

    if "error" in data:
        return templates.TemplateResponse(
            request=request,
            name="result_error.html",
            context={"error": data["error"]},
        )

    return templates.TemplateResponse(
        request=request,
        name="result_ok.html",
        context={"data": data},
    )


if __name__ == "__main__":
    import os
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    reload_flag = os.getenv("RELOAD", "false").lower() == "true"
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=reload_flag)