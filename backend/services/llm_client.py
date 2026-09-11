"""统一大模型调用层，消除 chat / llm 各处重复的『Gemini vs OpenAI 兼容』
分支与 HTTP 调用逻辑。config 统一使用 dict 形式。"""
import json
import httpx
from typing import Optional, List

ANTHROPIC_FALLBACK_MODELS = [
    "claude-3-5-sonnet-20240620",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
]


def _is_gemini(provider: str) -> bool:
    return "Gemini" in (provider or "")


def _to_gemini_contents(messages: List[dict]) -> List[dict]:
    """中立消息 → Gemini contents（user 之外统一映射为 model）。"""
    return [
        {"role": "user" if m.get("role") == "user" else "model",
         "parts": [{"text": m.get("text", "") or ""}]}
        for m in messages
    ]


def _to_openai_messages(messages: List[dict]) -> List[dict]:
    """中立消息 → OpenAI chat messages，支持工具调用/结果与首条 system。"""
    oai_messages = []
    for idx, m in enumerate(messages):
        role = m.get("role")
        if role == "tool_result":
            oai_messages.append({"role": "tool", "tool_call_id": m.get("tool_call_id", "call_0"),
                                 "content": m.get("text", "")})
        elif role == "assistant":
            msg = {"role": "assistant", "content": m.get("text", "") or ""}
            if m.get("tool_call"):
                tc = m["tool_call"]
                msg["tool_calls"] = [{"id": m.get("tool_call_id", "call_0"), "type": "function",
                                      "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}]
                msg["content"] = None
            oai_messages.append(msg)
        elif role == "user":
            oai_messages.append({"role": "user", "content": m.get("text", "")})
        else:
            # 首条模型/系统提示统一作为 system
            oai_messages.append({"role": "system", "content": m.get("text", "")})
    return oai_messages


async def list_models(config: dict) -> List[str]:
    """拉取可用模型列表。Anthropic 无标准 /models 端点时回退到内置列表；
    其它 provider 失败则抛 ValueError（由调用方转成 HTTP 错误）。"""
    provider = config.get("provider", "")
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if _is_gemini(provider):
                resp = await client.get(f"{base_url}/v1beta/models?key={api_key}")
                resp.raise_for_status()
                return [
                    m["name"].replace("models/", "")
                    for m in resp.json().get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
            resp = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
    except Exception as e:
        if "Anthropic" in provider:
            return list(ANTHROPIC_FALLBACK_MODELS)
        raise ValueError(f"获取模型列表失败: {str(e)}")


async def _gemini_chat_with_tools(config: dict, messages: List[dict], tools: List[dict]) -> dict:
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key")
    model = config.get("model_name")
    gemini_tools = [{"function_declarations": [
        {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
        for t in tools
    ]}]
    url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"contents": _to_gemini_contents(messages), "tools": gemini_tools})
        resp.raise_for_status()
        parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        if "functionCall" in part:
            fc = part["functionCall"]
            return {"tool_call": {"name": fc["name"], "arguments": fc.get("args", {})}}
    text = "".join(p.get("text", "") for p in parts)
    return {"text": text or "未获取到回复内容"}


async def _openai_chat_with_tools(config: dict, messages: List[dict], tools: List[dict]) -> dict:
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key")
    model = config.get("model_name")
    oai_tools = [
        {"type": "function", "function": {"name": t["name"], "description": t["description"],
                                          "parameters": t["parameters"]}}
        for t in tools
    ]
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": _to_openai_messages(messages),
                  "tools": oai_tools, "tool_choice": "auto"},
        )
        print(f"chat/completions resp: {resp.json()}")
        resp.raise_for_status()
        msg = resp.json().get("choices", [{}])[0].get("message", {})
    if msg.get("tool_calls"):
        tc = msg["tool_calls"][0]
        return {"tool_call": {"name": tc["function"]["name"],
                              "arguments": json.loads(tc["function"]["arguments"]),
                              "tool_call_id": tc["id"]}}
    return {"text": msg.get("content") or "未获取到回复内容"}


async def chat_with_tools(config: dict, messages: List[dict], tools: List[dict]) -> dict:
    """工具调用单轮。返回 {"text": str} 或 {"tool_call": {"name", "arguments", ...}}。"""
    if _is_gemini(config.get("provider", "")):
        return await _gemini_chat_with_tools(config, messages, tools)
    return await _openai_chat_with_tools(config, messages, tools)


async def openai_completion(
    config: dict, messages: List[dict], response_format: Optional[dict] = None, timeout: float = 60.0
) -> str:
    """OpenAI 兼容 /chat/completions 原始调用（支持多模态 content 数组）。
    返回 message.content 字符串，失败抛异常。"""
    payload = {"model": config["model_name"], "messages": messages}
    if response_format:
        payload["response_format"] = response_format

    url = f"{config['base_url'].rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]


async def _gemini_completion(config: dict, messages: List[dict], timeout: float = 60.0) -> str:
    """Gemini 纯文本补全（generateContent，无工具）。返回文本，失败抛异常。"""
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key")
    model = config.get("model_name")
    url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json={"contents": _to_gemini_contents(messages)})
        resp.raise_for_status()
        parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


async def complete(config: dict, messages: List[dict], timeout: float = 60.0) -> str:
    """provider 无关的纯文本补全（无工具调用），供会话总结等场景使用。
    Gemini 走 generateContent，其它 OpenAI 兼容 provider 走 openai_completion。
    messages 为中立格式 [{"role": "user"/"model"/..., "text": ...}]。"""
    if _is_gemini(config.get("provider", "")):
        return await _gemini_completion(config, messages, timeout=timeout)
    return await openai_completion(config, _to_openai_messages(messages), timeout=timeout)
