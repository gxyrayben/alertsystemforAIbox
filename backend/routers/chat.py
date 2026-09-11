from fastapi import APIRouter, HTTPException, Depends
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.schemas import ChatRequest
from models.db import get_db
from models.orm import DeviceORM, ConversationORM
from services import llm_client, conversation_service as convo, skills
from services.agent_tools import TOOLS, execute_tool
import database

router = APIRouter(tags=["chat"])

# 系统提示词的技能段落由技能注册表统一生成（新增技能只需改 services/skills.py）
SYSTEM_PROMPT = skills.build_skills_prompt()

# 会话记忆参数
SUMMARY_TRIGGER = 6   # 会话消息数达到此值后开始维护滚动总结
HISTORY_KEEP = 8      # 发给大模型的最近消息条数上限（更早内容由 summary 承载）


# 会以表格形式回传前端的查询类工具 → 表格列定义
_TABLE_SPECS = {
    "get_device_streams": {
        "data_key": "channels",
        "title": "视频流通道",
        "columns": [
            {"key": "device_id", "label": "通道ID"},
            {"key": "device_name", "label": "通道名称"},
            {"key": "proto", "label": "协议"},
            {"key": "rtsp", "label": "取流地址"},
            {"key": "onlinestatus", "label": "在线状态"},
        ],
    },
    "get_device_control_tasks": {
        "data_key": "tasks",
        "title": "已布控任务",
        "columns": [
            {"key": "task_id", "label": "任务ID"},
            {"key": "task_name", "label": "任务名称"},
            {"key": "task_type", "label": "任务类型"},
            {"key": "camera_device_name", "label": "通道名称"},
            {"key": "task_status", "label": "任务状态"},
            {"key": "algorithms", "label": "关联智能体/算法"},
            {"key": "action", "label": "操作", "type": "action"},
        ],
    },
    "check_algorithm_authorization": {
        "data_key": "authorizations",
        "title": "算法授权（整机）",
        "columns": [
            {"key": "package_name", "label": "算法包"},
            {"key": "desp", "label": "说明"},
        ],
    },
    "list_device_algorithms": {
        "data_key": "algorithms",
        "title": "可布控小模型算法",
        "columns": [
            {"key": "algoCabinName", "label": "算法仓"},
            {"key": "version", "label": "版本"},
            {"key": "eventName", "label": "算法名称"},
            {"key": "eventType", "label": "事件类型(ID)"},
            {"key": "targetTypes", "label": "检测目标"},
            {"key": "description", "label": "说明"},
        ],
    },
    "resolve_algorithm": {
        "data_key": "matches",
        "title": "算法名称匹配",
        "columns": [
            {"key": "event_name", "label": "算法名称"},
            {"key": "minor_type", "label": "算法ID(event_type)"},
            {"key": "major_name", "label": "所属大类"},
            {"key": "major_type", "label": "大类ID"},
        ],
    },
    "list_agents": {
        "data_key": "agents",
        "title": "智能体算法（整机）",
        "columns": [
            {"key": "event_id", "label": "智能体ID"},
            {"key": "event_tag", "label": "名称"},
            {"key": "alarm_type", "label": "报警类型"},
            {"key": "prompt_preview", "label": "提示词预览"},
        ],
    },
}


def _build_table(tool_name: str, result_text: str):
    """把查询类工具的 JSON 结果转成前端可直接渲染的表格结构，非表格工具返回 None。"""
    spec = _TABLE_SPECS.get(tool_name)
    if not spec:
        return None
    try:
        data = json.loads(result_text)
    except Exception:
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    rows = data.get(spec["data_key"], []) or []
    return {
        "title": f"{spec['title']}（共 {data.get('count', len(rows))} 项）",
        "columns": spec["columns"],
        "rows": rows,
    }



async def _build_system_prompt(db: AsyncSession, device_id: str, summary: str = "") -> str:
    """组装系统提示：技能段（含全局约束）+ 会话记忆 + 当前设备上下文。
    - summary：本会话滚动记忆，使早期被压缩的内容仍可被智能体感知；
    - device_id：绑定设备后，用户无需每次重复 device_id。"""
    prompt = SYSTEM_PROMPT
    if summary:
        prompt += f"\n\n【会话记忆/已知上下文】以下是本会话早前内容的滚动总结，请结合它理解用户当前需求：\n{summary}"
    if not device_id:
        return prompt
    device = (await db.execute(
        select(DeviceORM).where(DeviceORM.device_id == device_id)
    )).scalar_one_or_none()
    if not device:
        return prompt
    return (
        prompt
        + f"\n\n【当前会话上下文】用户正在管理设备「{device.name}」(device_id={device.device_id})。"
        + "当用户未明确指定设备时，默认对该设备进行查询、创建或修改任务操作，"
        + "调用各工具时请直接使用该 device_id。"
    )


async def _load_conversation_summary(db: AsyncSession, conversation_id: str) -> str:
    """读取已存在会话的滚动记忆；新会话返回空串。"""
    if not conversation_id:
        return ""
    conv = await db.get(ConversationORM, conversation_id)
    return (conv.summary or "") if conv else ""


def _compress_messages(messages: list) -> list:
    """长对话时只发送最近 HISTORY_KEEP 条消息，更早内容由系统提示中的会话记忆承载。"""
    if len(messages) <= HISTORY_KEEP:
        return messages
    return messages[-HISTORY_KEEP:]


async def _summarize_conversation(config: dict, prev_summary: str, messages: list) -> str:
    """基于已有总结 + 最近对话，产出一份中文滚动总结。失败由调用方兜底。"""
    transcript = "\n".join(
        f"{'用户' if m.get('role') == 'user' else '助手'}：{(m.get('text') or '').strip()}"
        for m in messages if (m.get("text") or "").strip()
    )
    sys = ("你是会话记忆维护助手。请基于【已有总结】与【最新对话】，输出一份中文滚动总结，"
           "要点覆盖：涉及的设备、用户目标、已确认的关键参数/选择、已完成或待办的布控动作。"
           "控制在 200 字以内，只输出总结正文，不要任何解释或前后缀。")
    user = f"【已有总结】\n{prev_summary or '（无）'}\n\n【最新对话】\n{transcript}"
    msgs = [{"role": "model", "text": sys}, {"role": "user", "text": user}]
    return (await llm_client.complete(config, msgs)).strip()


async def _maybe_refresh_summary(db: AsyncSession, config: dict, conv: ConversationORM, prev_summary: str) -> str:
    """会话足够长时刷新滚动记忆（best-effort：失败保持旧总结，不影响主流程）。"""
    msgs = await convo.get_messages(db, conv.id)
    if len(msgs) < SUMMARY_TRIGGER:
        return prev_summary
    recent = [{"role": m.role, "text": m.text} for m in msgs[-HISTORY_KEEP:]]
    try:
        new_summary = await _summarize_conversation(config, prev_summary, recent)
        if new_summary:
            await convo.update_summary(db, conv, new_summary)
            return new_summary
    except Exception as e:
        print(f"Summary refresh skipped: {e}")
    return prev_summary


async def _run_agent(config, user_messages, db: AsyncSession, system_prompt: str):
    """执行 agent loop（最多 5 轮工具调用），返回 (最终文字回复, 表格列表, 布控方案)。"""
    messages = [{"role": "model", "text": system_prompt}] + list(user_messages)
    tables = []
    proposal = None
    for _ in range(5):
        #print(f"before chat_with_tools: {messages}")
        result = await llm_client.chat_with_tools(config, messages, TOOLS)
        print(f"after chat_with_tools: {result}")
        if "text" in result:           # if this is a result solution, return to userspace
            return result["text"], tables, proposal

        tc = result["tool_call"]       # else  ,need to call tools to get next data ;
        tool_result = await execute_tool(tc["name"], tc.get("arguments", {}), db)
        print(f"after execute_tool: {tool_result}")
        table = _build_table(tc["name"], tool_result)
        if table:
            tables.append(table)
        if tc["name"] == "propose_deployment":
            try:
                data = json.loads(tool_result)
                if isinstance(data, dict) and data.get("proposal"):
                    proposal = data["proposal"]
            except Exception:
                pass
        messages.append({"role": "assistant", "text": None, "tool_call": tc,
                         "tool_call_id": tc.get("tool_call_id", "call_0")})
        messages.append({"role": "tool_result", "text": tool_result,
                         "tool_call_id": tc.get("tool_call_id", "call_0")})
    return "处理超时，请重试。", tables, proposal



@router.get("/skills")
async def get_skills():
    """返回智能体已具备的技能元数据，供前端技能面板渲染。"""
    return {"skills": skills.public_skills()}


@router.post("/chat")
async def chat_with_ai(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    config = database.llm_config
    if not config or not config.get("api_key") or not config.get("model_name"):
        raise HTTPException(status_code=400, detail="请先在模型配置界面配置并保存 API Key 和模型")

    # 取本轮用户输入（messages 最后一条 user）用于持久化 & 会话自动命名
    last_user = next((m for m in reversed(request.messages) if m.get("role") == "user"), None)
    user_text = last_user.get("text", "") if last_user else ""

    # 会话记忆：注入已存滚动总结 + 压缩历史（更早内容由总结承载）
    prev_summary = await _load_conversation_summary(db, request.conversation_id)
    system_prompt = await _build_system_prompt(db, request.device_id, prev_summary)
    agent_messages = _compress_messages(request.messages)

    try:
        reply_text, tables, proposal = await _run_agent(config, agent_messages, db, system_prompt)
    except Exception as e:
        print(f"Agent Error: {e}")
        raise HTTPException(status_code=500, detail=f"与大模型通信失败: {str(e)}")

    # 持久化：确保会话存在 -> 存用户消息 -> 存助手回复 -> 更新会话时间
    conv = await convo.ensure_conversation(db, request.conversation_id, title_hint=user_text)
    if user_text:
        await convo.add_message(db, conv.id, "user", user_text)
    await convo.add_message(db, conv.id, "model", reply_text, tables=json.dumps(tables, ensure_ascii=False))
    await convo.touch_conversation(db, conv)
    await db.flush()

    # 刷新滚动记忆（会话够长时；best-effort，不影响回复）
    summary = await _maybe_refresh_summary(db, config, conv, prev_summary)
    await db.commit()

    return {"text": reply_text, "conversation_id": conv.id, "tables": tables,
            "proposal": proposal, "summary": summary}
