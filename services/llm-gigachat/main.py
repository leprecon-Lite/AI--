from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from GigaChatService import GigaChatService
from storage import (
    get_recent_protocols,
    get_protocol_details,
    get_stats,
    get_protocols_filtered,
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


@app.get("/")
def say_hello():
    return {"message": "hello, world!"}


@app.post("/check/")
async def check_file(file: UploadFile = File(...)):
    """Основной эндпоинт: маппинг + проверка + отчёт GigaChat + сохранение."""
    try:
        return await gigachat.upload_document(file)
    except Exception as e:
        logger.exception("Ошибка обработки файла")
        return {"error": str(e)}


@app.post("/explain/")
def explain(req: ExplainRequest):
    """RAG-объяснение причин отклонения для оператора."""
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


# ---------- Админ-API ----------

@app.get("/admin/stats")
def admin_stats():
    try:
        return get_stats()
    except Exception as e:
        logger.exception("Ошибка статистики")
        return {"error": str(e)}


@app.get("/admin/protocols")
def admin_protocols(status: str = "", limit: int = 50):
    try:
        items = get_protocols_filtered(status=status, limit=limit)
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.exception("Ошибка списка протоколов")
        return {"error": str(e)}


@app.get("/admin/rules")
def admin_rules():
    """Список нормативов (без тяжёлого поля text)."""
    result = []
    for r in gigachat.rules:
        result.append({
            "id": r.get("id"),
            "standard": r.get("standard"),
            "clause": r.get("clause"),
            "category": r.get("category"),
            "parameter": r.get("parameter"),
            "operator": r.get("operator"),
            "value": r.get("value"),
            "unit": r.get("unit"),
        })
    return {"items": result, "total": len(result)}


@app.get("/admin/config")
def admin_config():
    from config import settings
    return {
        "giga_model": settings.giga_model,
        "giga_scope": settings.giga_scope,
        "warning_tolerance_percent": settings.warning_tolerance_percent,
        "log_level": settings.log_level,
        "rules_path": settings.rules_path,
        "db_path": settings.db_path,
    }


@app.put("/admin/rules/{rule_id}")
def admin_update_rule(rule_id: str, payload: RuleUpdate):
    rule = gigachat.rules_by_id.get(rule_id)
    if not rule:
        raise HTTPException(404, f"Норматив {rule_id} не найден")

    if payload.value is not None:
        rule["value"] = payload.value
    if payload.aliases is not None:
        rule["aliases"] = payload.aliases

    from classifier import build_alias_index
    gigachat.alias_index = build_alias_index(gigachat.rules)

    logger.info("Правило %s обновлено в памяти", rule_id)
    return {"status": "ok", "rule": rule}


if __name__ == "__main__":
    import os
    import uvicorn
    from config import settings
    host = os.getenv("HOST", "127.0.0.1")
    reload_flag = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=settings.giga_port, reload=reload_flag)