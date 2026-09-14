from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from GigaChatService import GigaChatService
from storage import get_recent_protocols, get_protocol_details
from logger import logger

app = FastAPI(title="LLM GigaChat Service")
gigachat = GigaChatService()


class ExplainRequest(BaseModel):
    rule_id: str
    actual: str | float | int


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

if __name__ == "__main__":
    import os
    import uvicorn
    from config import settings
    host = os.getenv("HOST", "127.0.0.1")
    reload_flag = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=settings.giga_port, reload=reload_flag)