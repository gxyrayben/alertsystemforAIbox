from fastapi import APIRouter
from models.schemas import ChatRequest

router = APIRouter(tags=["chat"])

@router.post("/chat")
async def chat_with_ai(request: ChatRequest):
    import asyncio
    await asyncio.sleep(1)
    
    last_user_msg = request.messages[-1]["text"]
    response_text = f"（后端模拟回复）关于您提到的 '{last_user_msg}'，我建议您检查相关设备的网络配置。如有更多问题，请随时提问。"
    
    return {"text": response_text}
