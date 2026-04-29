import httpx
import json
import database

class LLMService:
    @staticmethod
    async def optimize_prompt(target_agent_id: str, current_prompt: str, images_data: list):
        """
        Optimize prompt using LLM with multiple images.
        images_data: list of data URLs (e.g. "data:image/jpeg;base64,...")
        """
        config = database.llm_config
        if not config:
            return None
        
        prompt_instruction = f"""你现在是一个智能安防摄像头的提示词调优专家。
当前设备的任务是识别：{target_agent_id}。
设备目前使用的识别提示词(Prompt)是：
{current_prompt}

请观察用户提供的最新 {len(images_data)} 张『告警抓拍图』。
1. 综合判断这些图中是否存在**误报**（False Positive）？
2. 如果存在误报，请分析原因（如反光、形状相似等），并输出一段**全新优化后的 Prompt**，在原基础上增加排除这些干扰项的描述。如果不希望修改或者并非误报，请在optimized_prompt保持原样。

请严格以 JSON 格式返回：
{{
    "is_false_positive": true/false,
    "reason": "分析原因...",
    "optimized_prompt": "新的提示词内容..."
}}"""
        
        content_array = [{"type": "text", "text": prompt_instruction}]
        for img_url in images_data:
            content_array.append({"type": "image_url", "image_url": {"url": img_url}})
        
        messages = [{"role": "user", "content": content_array}]
        
        llm_payload = {
            "model": config["model_name"],
            "messages": messages,
            "response_format": {"type": "json_object"} if ("gpt" in config["model_name"].lower() or "moonshot" in config["model_name"].lower()) else None
        }
        if llm_payload["response_format"] is None:
            del llm_payload["response_format"]

        headers = {"Authorization": f"Bearer {config['api_key']}"}
        llm_url = f"{config['base_url'].rstrip('/')}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(llm_url, headers=headers, json=llm_payload)
                if res.status_code == 200:
                    llm_data = res.json()
                    content_str = llm_data["choices"][0]["message"]["content"].strip()
                    if content_str.startswith("```json"):
                        content_str = content_str[7:-3].strip()
                    elif content_str.startswith("```"):
                        content_str = content_str[3:-3].strip()
                    
                    return json.loads(content_str)
                else:
                    print(f"[LLMService] Non-200 response: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[LLMService] Error: {e}")
        return None
