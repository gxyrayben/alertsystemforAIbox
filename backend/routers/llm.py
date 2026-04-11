from fastapi import APIRouter, HTTPException
import database
from models.schemas import LLMConfig
import httpx

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
    models = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if "Gemini" in config.provider:
                # Gemini API
                url = f"{config.base_url.rstrip('/')}/v1beta/models?key={config.api_key}"
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                models = [m["name"].replace("models/", "") for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
            else:
                # OpenAI Compatible API (Moonshot, DeepSeek, Zhipu, StepFun, MiniMax, Local, etc.)
                url = f"{config.base_url.rstrip('/')}/models"
                headers = {"Authorization": f"Bearer {config.api_key}"}
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                models = [m["id"] for m in data.get("data", [])]
    except Exception as e:
        # Anthropic does not have a standard /models endpoint in their native API, fallback gracefully
        if "Anthropic" in config.provider:
            models = ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-haiku-20240307"]
        else:
            raise HTTPException(status_code=400, detail=f"获取模型列表失败: {str(e)}")
            
    return {"models": models}
