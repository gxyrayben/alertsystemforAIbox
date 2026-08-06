from fastapi import APIRouter, HTTPException
import database
from models.schemas import LLMConfig
from services import llm_client

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config", response_model=LLMConfig)
async def get_llm_config():
    return database.llm_config


@router.post("/config")
async def update_llm_config(config: LLMConfig):
    database.llm_config = config.dict()
    database.save_config()
    return database.llm_config


@router.post("/models")
async def fetch_models(config: LLMConfig):
    try:
        models = await llm_client.list_models(config.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"models": models}
