from fastapi import APIRouter
import database
from models.schemas import ServicesConfig
import services_manager

router = APIRouter(prefix="/services", tags=["services"])

@router.get("/config", response_model=ServicesConfig)
async def get_services_config():
    return database.current_services_config

@router.post("/config")
async def update_services_config(config: ServicesConfig):
    old_config = database.current_services_config.copy()
    database.current_services_config = config.dict()
    database.save_config()
    
    # Check if we need to reload WS
    if old_config.get("ws") != database.current_services_config.get("ws"):
        await services_manager.reload_ws_service()
        
    # Check if we need to reload HTTP
    if old_config.get("http") != database.current_services_config.get("http"):
        await services_manager.reload_http_service()
        
    return database.current_services_config
