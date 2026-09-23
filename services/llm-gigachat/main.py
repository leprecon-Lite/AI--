from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, Any, List
from GigaChatService import GigaChatService
from storage import (
    get_recent_protocols, get_protocol_details, get_stats, get_protocols_filtered,
    get_active_rules_version, get_all_rules_versions,
    get_audit_log, log_action, export_history_rows, get_users,
)
from logger import logger

app = FastAPI(title="LLM GigaChat Service")
gigachat = GigaChatService()


class ExplainRequest(BaseModel):
    rule_id: str
    actual: str | float | int


class RuleUpdate(BaseModel):
    value: Optional[Any] = None
    aliases: Optional[list] = None
    operator: Optional[str] = None
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None


class AssistantRequest(BaseModel):
    question: str


class GenerateAliasesRequest(BaseModel):
    parameter: str
    unit: str = ""


@app.get("/")
def say_hello():
    return {"message": "hello, world!"}


@app.post("/check/")
async def check_file(file: UploadFile = File(...)):
    try:
        return await gigachat.upload_document(file)
    except Exception as e:
        logger.exception("Ошибка обработки файла")
        return {"error": str(e)}


@app.post("/explain/")
def explain(req: ExplainRequest):
    try:
        return gigachat.explain_deviation(req.rule_id, req.actual)
    except Exception as e:
        logger.exception("Ошибка объяснения")
        return {"error": str(e)}


@app.get("/history/")
def history(limit: int = 20):
    return {"items": get_recent_protocols(limit)}


@app.get("/history/{protocol_id}")
def history_item(protocol_id: int):
    return get_protocol_details(protocol_id)


@app.get("/export/pdf/{protocol_id}")
def export_pdf(protocol_id: int):
    pdf_bytes = gigachat.export_protocol_pdf(protocol_id)
    if pdf_bytes is None:
        raise HTTPException(404, "Протокол не найден")

    log_action("export_pdf", "protocol", str(protocol_id))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="protocol_{protocol_id}.pdf"'},
    )


# ---------- Админ ----------

@app.get("/admin/stats")
def admin_stats():
    return get_stats()


@app.get("/admin/protocols")
def admin_protocols(status: str = "", limit: int = 50):
    return {"items": get_protocols_filtered(status=status, limit=limit)}


@app.get("/admin/rules")
def admin_rules():
    return {"items": [{
        "id": r.get("id"), "standard": r.get("standard"), "clause": r.get("clause"),
        "category": r.get("category"), "parameter": r.get("parameter"),
        "aliases": r.get("aliases", []), "operator": r.get("operator"),
        "value": r.get("value"), "unit": r.get("unit"), "text": r.get("text"),
    } for r in gigachat.rules], "total": len(gigachat.rules)}


@app.get("/admin/rules/{rule_id}")
def admin_rule_detail(rule_id: str):
    rule = gigachat.rules_by_id.get(rule_id)
    if not rule:
        raise HTTPException(404, f"Норматив {rule_id} не найден")
    return rule


@app.put("/admin/rules/{rule_id}")
def admin_update_rule(rule_id: str, payload: RuleUpdate):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Нечего обновлять")
    ok = gigachat.update_rule_in_file(rule_id, updates)
    if not ok:
        raise HTTPException(404, f"Норматив {rule_id} не сохранён")
    log_action("update_rule", "rule", rule_id, f"fields: {list(updates.keys())}")
    return {"status": "ok", "rule": gigachat.rules_by_id.get(rule_id)}


@app.get("/admin/rules/version")
def admin_rules_version():
    return {"active": get_active_rules_version(), "all": get_all_rules_versions()}


@app.get("/admin/config")
def admin_config():
    from config import settings
    return {
        "giga_model": settings.giga_model, "giga_scope": settings.giga_scope,
        "warning_tolerance_percent": settings.warning_tolerance_percent,
        "log_level": settings.log_level, "rules_path": settings.rules_path,
        "db_path": settings.db_path,
    }


@app.post("/admin/rules/upload")
async def admin_upload_rules(file: UploadFile = File(...)):
    try:
        content = await file.read()
        from pathlib import Path
        upload_path = Path(__file__).parent / f"uploaded_{file.filename}"
        with open(upload_path, "wb") as f:
            f.write(content)
        result = gigachat.reload_rules_from_file(file.filename)
        if "error" not in result:
            log_action("upload_rules", "rules", file.filename, f"count={result.get('count')}")
        return result
    except Exception as e:
        logger.exception("Ошибка загрузки нормативов")
        return {"error": str(e)}


@app.post("/admin/assistant")
def admin_assistant(req: AssistantRequest):
    try:
        result = gigachat.ask_assistant(req.question)
        if "answer" in result:
            log_action("assistant_query", "assistant", "", req.question[:100])
        return result
    except Exception as e:
        return {"error": str(e)}


@app.post("/admin/rules/generate_aliases")
def admin_generate_aliases(req: GenerateAliasesRequest):
    try:
        return {"aliases": gigachat.generate_aliases(req.parameter, req.unit)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/admin/audit")
def admin_audit(limit: int = 100):
    return {"items": get_audit_log(limit)}


@app.get("/admin/export/history")
def admin_export_history():
    return {"rows": export_history_rows()}


@app.get("/admin/users")
def admin_users():
    return {"items": get_users()}


if __name__ == "__main__":
    import os
    import uvicorn
    from config import settings
    host = os.getenv("HOST", "127.0.0.1")
    reload_flag = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=settings.giga_port, reload=reload_flag)