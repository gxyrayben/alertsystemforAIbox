from fastapi import APIRouter, HTTPException
from models.schemas import ChatRequest
import database
import httpx

router = APIRouter(tags=["chat"])

@router.post("/chat")
async def chat_with_ai(request: ChatRequest):
    config = database.llm_config
    if not config or not config.get("api_key") or not config.get("model_name"):
        raise HTTPException(status_code=400, detail="请先在模型配置界面配置并保存 API Key 和模型")

    provider = config.get("provider", "")
    api_key = config.get("api_key")
    base_url = config.get("base_url", "").rstrip('/')
    model_name = config.get("model_name")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if "Gemini" in provider:
                # Gemini API Format
                url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={api_key}"
                contents = []
                for msg in request.messages:
                    role = msg.get("role")
                    text = msg.get("text")
                    contents.append({
                        "role": "user" if role == "user" else "model",
                        "parts": [{"text": text}]
                    })
                
                payload = {
                    "contents": contents
                }
                
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                candidates = data.get("candidates", [])
                if candidates and candidates[0].get("content", {}).get("parts"):
                    response_text = candidates[0]["content"]["parts"][0].get("text", "")
                else:
                    response_text = "未获取到回复内容"
                    
            else:
                # OpenAI Compatible API Format
                url = f"{base_url}/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}"}
                
                messages = []
                for msg in request.messages:
                    role = msg.get("role")
                    text = msg.get("text")
                    messages.append({
                        "role": "user" if role == "user" else "assistant",
                        "content": text
                    })
                
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.7
                }
                
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                choices = data.get("choices", [])
                if choices and choices[0].get("message", {}).get("content"):
                    response_text = choices[0]["message"]["content"]
                else:
                    response_text = "未获取到回复内容"

    except Exception as e:
        print(f"Chat API Error: {e}")
        raise HTTPException(status_code=500, detail=f"与大模型通信失败: {str(e)}")
        
    return {"text": response_text}
