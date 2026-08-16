"""把即将退出近期上下文的原图转换成 RunningSummary 视觉记忆。"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.game_agent.models import VisualMemory
from app.game_agent.prompts import IMAGE_SUMMARY_PROMPT
from app.game_agent.structured import invoke_validated_json


class ImageMemoryService:
    """仅在图片所属旧轮次被压缩时调用视觉模型。"""

    def __init__(self, vision_model: BaseChatModel):
        self.vision_model = vision_model

    async def summarize(self, image: str, source_message_id: str) -> VisualMemory:
        content = [
            {"type": "text", "text": IMAGE_SUMMARY_PROMPT},
            {"type": "image_url", "image_url": {"url": image}},
        ]
        try:
            memory = await invoke_validated_json(
                self.vision_model,
                VisualMemory,
                [HumanMessage(content=content)],
            )
            memory.source_message_id = source_message_id
            return memory
        except Exception:
            return VisualMemory(
                source_message_id=source_message_id,
                key_facts=["历史图片未能生成可靠的结构化摘要。"],
                uncertainty="如需回答图片细节，需要从数据库重新加载原图。",
            )
