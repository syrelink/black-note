"""语言模型结构化输出适配器。

模型返回的是不可信文本，本模块负责要求 JSON、解析 JSON，并通过 Pydantic
Schema 校验，给图片摘要、记忆压缩和搜索规划提供统一的类型安全边界。
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


async def invoke_validated_json(
    model: BaseChatModel,
    schema: type[SchemaT],
    messages: list[BaseMessage],
    max_tokens: int | None = None,
) -> SchemaT:
    """调用模型并将结果验证为指定 Pydantic 类型。

    优先解析完整响应；部分兼容模型会在 JSON 外添加说明，因此解析失败时会
    尝试提取第一个 JSON 对象。最终仍必须通过 schema.model_validate。
    """
    # 动态附加 Schema，而不是在每一份业务 Prompt 中重复维护字段说明。
    schema_instruction = (
        "只输出一个合法 JSON 对象，不要 Markdown 代码块，不要解释。"
        f"JSON 必须符合以下 Schema：{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )
    runnable = model.bind(max_tokens=max_tokens) if max_tokens else model
    response = await runnable.ainvoke(messages + [HumanMessage(content=schema_instruction)])
    content = response.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        # 这是兼容性兜底，不会绕过下方 Pydantic 字段校验。
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ValueError(f"模型未返回 JSON：{content[:300]}")
        payload = json.loads(match.group(0))
    return schema.model_validate(payload)
