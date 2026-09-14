import os
import logging
import httpx
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent.gateway")

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
    allow_methods=["GET", "POST", "OPTIONS", "PUT"],
    allow_headers=["*"],
)

GIGA_SERVICE_URL = os.getenv("GIGA_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class ExplainRequest(BaseModel):
    rule_id: str
    actual: str | float | int


# ---------- HTML-страницы ----------

@app.get("/", response_class=HTMLResponse)
async def serve_demo():
    """Главная страница — demo.html."""
    return FileResponse(Path(__file__).parent / "demo.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """
    Админ-панель. Все данные рендерятся на сервере через Jinja2 —
    никакого клиентского JS, никаких fetch-запросов.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r1 = await client.get(f"{GIGA_SERVICE_URL}/admin/stats")
            r2 = await client.get(f"{GIGA_SERVICE_URL}/admin/protocols", params={"limit": 50})
            r3 = await client.get(f"{GIGA_SERVICE_URL}/admin/rules")
            r4 = await client.get(f"{GIGA_SERVICE_URL}/admin/config")

            stats = r1.json() if r1.status_code == 200 else {"total": 0, "good": 0, "warning": 0, "defect": 0, "top_fails": []}
            protocols = r2.json().get("items", []) if r2.status_code == 200 else []
            rules = r3.json().get("items", []) if r3.status_code == 200 else []
            config = r4.json() if r4.status_code == 200 else {
                "giga_model": "—", "giga_scope": "—",
                "warning_tolerance_percent": 0,
                "log_level": "—", "rules_path": "—", "db_path": "—",
            }
        except Exception as e:
            logger.exception("Ошибка загрузки данных админки: %s", e)
            stats = {"total": 0, "good": 0, "warning": 0, "defect": 0, "top_fails": []}
            protocols = []
            rules = []
            config = {
                "giga_model": "—", "giga_scope": "—",
                "warning_tolerance_percent": 0,
                "log_level": "—", "rules_path": "—", "db_path": "—",
            }

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "stats": stats,
            "protocols": protocols,
            "rules": rules,
            "config": config,
        },
    )


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


# ---------- Админ-API (прокси, оставлены для совместимости) ----------

@app.get("/admin/api/stats")
async def proxy_admin_stats():
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{GIGA_SERVICE_URL}/admin/stats")
        return r.json()


@app.get("/admin/api/protocols")
async def proxy_admin_protocols(status: str = "", limit: int = 50):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{GIGA_SERVICE_URL}/admin/protocols",
            params={"status": status, "limit": limit},
        )
        return r.json()


@app.get("/admin/api/rules")
async def proxy_admin_rules():
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{GIGA_SERVICE_URL}/admin/rules")
        return r.json()


@app.get("/admin/api/config")
async def proxy_admin_config():
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{GIGA_SERVICE_URL}/admin/config")
        return r.json()


@app.put("/admin/api/rules/{rule_id}")
async def proxy_admin_update_rule(rule_id: str, payload: dict = Body(...)):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.put(
            f"{GIGA_SERVICE_URL}/admin/rules/{rule_id}",
            json=payload,
        )
        return r.json()


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    reload_flag = os.getenv("RELOAD", "false").lower() == "true"
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=reload_flag)