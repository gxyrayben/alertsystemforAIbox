import json
import database
from services.llm_client import openai_completion


class LLMService:
    @staticmethod
    async def optimize_prompt(target_agent_id: str, current_prompt: str, images_data: list):
        """使用多图调用大模型优化识别提示词。
        images_data: data URL 列表（如 "data:image/jpeg;base64,..."）。"""
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

        model_name = config["model_name"].lower()
        response_format = {"type": "json_object"} if ("gpt" in model_name or "moonshot" in model_name) else None

        try:
            content_str = (await openai_completion(config, messages, response_format)).strip()
            if content_str.startswith("```json"):
                content_str = content_str[7:-3].strip()
            elif content_str.startswith("```"):
                content_str = content_str[3:-3].strip()
            return json.loads(content_str)
        except Exception as e:
            print(f"[LLMService] Error: {e}")
        return None

    @staticmethod
    async def analyze_smallmodel_params(event_id: str, current: dict, samples: list):
        """小模型算法参数结构化调优（告警反馈闭环 Case2/Case3）。

        综合正报(应保留)与误报(应抑制)的目标尺寸分布 + 当前检测参数，给出更合理的
        检测阈值 / 目标框大小。纯文本结构化分析（不发图，仅发尺寸统计），省 token 且更稳。

        current: {threshold, target_max, target_min}
        samples: [{label: 'valid'|'false_positive', crop_w, crop_h, ratio}]
        返回: {threshold, target_max, target_min, reason} 或 None。
        """
        config = database.llm_config
        if not config:
            return None

        valid = [s for s in samples if s.get("label") == "valid"]
        fp = [s for s in samples if s.get("label") == "false_positive"]

        def _fmt(items):
            if not items:
                return "（无）"
            return "; ".join(
                f"{s.get('crop_w', '?')}x{s.get('crop_h', '?')}px"
                + (f", 占帧比例{s['ratio']:.3f}" if isinstance(s.get("ratio"), (int, float)) else "")
                for s in items
            )

        prompt_instruction = f"""你是安防摄像头小模型检测算法的参数调优专家。
当前算法(event_id={event_id})的检测参数为：
- 检测阈值 threshold = {current.get('threshold')}（0~1，越高越严格、越不易触发）
- 目标最大尺寸 target_max = {current.get('target_max')}（0~1，目标框占画面比例）
- 目标最小尺寸 target_min = {current.get('target_min')}（0~1，目标框占画面比例）

用户标注样本的送检小图（目标裁切）尺寸如下：
【正报 · 应保留】共{len(valid)}个：{_fmt(valid)}
【误报 · 应抑制】共{len(fp)}个：{_fmt(fp)}

请综合分析：
1. 若误报目标普遍偏小/偏大而正报不然，据此收紧 target_min/target_max 把误报排除、同时不误伤正报；
2. 若误报与正报尺寸重叠，则通过适度提高 threshold 抑制误报；正报偏少或阈值本已偏高时避免过度收紧。
在保证正报仍能触发的前提下给出更合理的新值。

请严格以 JSON 返回（数值型，threshold 与 target_* 均保留两位小数，target_* 取值范围 0~1 且 target_min ≤ target_max）：
{{
    "threshold": 0.0,
    "target_max": 1.0,
    "target_min": 0.0,
    "reason": "调整依据..."
}}"""

        messages = [{"role": "user", "content": prompt_instruction}]
        model_name = config["model_name"].lower()
        response_format = {"type": "json_object"} if ("gpt" in model_name or "moonshot" in model_name) else None

        try:
            content_str = (await openai_completion(config, messages, response_format)).strip()
            if content_str.startswith("```json"):
                content_str = content_str[7:-3].strip()
            elif content_str.startswith("```"):
                content_str = content_str[3:-3].strip()
            return json.loads(content_str)
        except Exception as e:
            print(f"[LLMService] analyze_smallmodel_params Error: {e}")
        return None
