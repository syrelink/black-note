import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)

# ── 两个工具函数，普通Python函数 ──────────────────

def search_notes(query: str) -> str:
    """模拟搜索笔记"""
    # 假数据，模拟ChromaDB返回
    fake_db = {
        "技术": [
            {"id": "1", "title": "Redis缓存穿透", "summary": "用布隆过滤器解决"},
            {"id": "2", "title": "LeetCode刷题心路", "summary": "坚持每天一题"},
        ],
        "情绪": [
            {"id": "3", "title": "深夜emo", "summary": "感觉很累很孤独"},
            {"id": "4", "title": "假装没事的一天", "summary": "其实内心很崩溃"},
        ],
        "美食": [
            {"id": "5", "title": "椰子鸡火锅", "summary": "汤底清甜，鸡肉嫩滑"},
        ],
    }
    for key, notes in fake_db.items():
        if key in query:
            result = "\n".join([
                f"ID:{n['id']} 标题:{n['title']} 摘要:{n['summary']}"
                for n in notes
            ])
            return result
    return "未找到相关笔记"


def get_note_detail(note_id: str) -> str:
    """模拟获取笔记详情"""
    fake_detail = {
        "1": "标题：Redis缓存穿透\n内容：今天终于搞懂了，核心是用布隆过滤器拦截不存在的key，同时对空值设置短TTL，双重保险。",
        "2": "标题：LeetCode刷题心路\n内容：坚持刷题60天，从动态规划完全不会到现在能独立写出中等题，重复是最好的老师。",
        "3": "标题：深夜emo\n内容：凌晨两点睡不着，脑子里全是乱七八糟的事，感觉很累，但又说不清楚累在哪里。",
        "4": "标题：假装没事的一天\n内容：白天对所有人笑，晚上一个人发呆，这种状态持续很久了，需要出去走走。",
        "5": "标题：椰子鸡火锅\n内容：终于找到了那家店，椰子汤底真的绝，鸡肉嫩到不行，下次要再去。",
    }
    return fake_detail.get(note_id, f"笔记{note_id}不存在")

    # 这是OpenAI/DeepSeek的Function Calling格式
# 大模型靠读这个决定调用哪个工具、传什么参数
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "根据关键词语义搜索用户笔记，返回相关笔记列表和ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，例如：技术、情绪、美食"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_note_detail",
            "description": "根据笔记ID获取笔记完整内容，需要先用search_notes获取ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "笔记ID，从search_notes结果中获取"
                    }
                },
                "required": ["note_id"]
            }
        }
    }
]

# 工具名 → 函数的映射表
TOOL_MAP = {
    "search_notes":   search_notes,
    "get_note_detail": get_note_detail,
}

def run_react_agent(user_question: str, max_steps: int = 10):
    print(f"\n{'='*50}")
    print(f"用户问题：{user_question}")
    print(f"{'='*50}")

    # 对话历史，ReAct的核心就是维护这个列表
    messages = [
        {
            "role": "system",
            "content": (
                "你是用户的笔记助手。\n"
                "处理任务时：先搜索相关笔记，再读取需要的详情，最后整合回答。\n"
                "不要编造笔记中没有的内容。"
            )
        },
        {
            "role": "user",
            "content": user_question
        }
    ]

    step = 0

    # ── ReAct核心循环 ────────────────────────────
    while step < max_steps:
        step += 1
        print(f"\n--- 第{step}轮思考 ---")

        # 1. 让大模型思考：下一步做什么
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",  # 让模型自己决定用不用工具
        )

        msg = response.choices[0].message

        # 2. 判断大模型的决策
        if msg.tool_calls:
            # ── 情况A：大模型决定调用工具 ──────────
            # 先把大模型的决策加入历史
            messages.append({
                "role":       "assistant",
                "content":    msg.content,
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]
            })

            # 执行每个工具调用
            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                print(f"🔧 调用工具：{tool_name}")
                print(f"   参数：{tool_args}")

                # 执行工具
                tool_fn     = TOOL_MAP[tool_name]
                tool_result = tool_fn(**tool_args)

                print(f"   结果：{tool_result[:80]}...")

                # 把工具执行结果加入历史
                # 大模型下一轮能看到这个结果（Observation）
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      tool_result
                })

        else:
            # ── 情况B：大模型认为不需要工具，直接回答 ──
            final_answer = msg.content
            print(f"\n{'='*50}")
            print(f"🤖 最终回答：\n{final_answer}")
            print(f"{'='*50}")
            print(f"\n共执行了 {step} 轮思考")
            return final_answer

    print("⚠️ 达到最大步数限制")
    return None

if __name__ == "__main__":
    # 测试1：简单任务，一次搜索就够
    run_react_agent("我有哪些技术相关的笔记？")

    # 测试2：中等任务，需要搜索+读详情
    run_react_agent("找到我的Redis笔记，告诉我核心内容是什么")

    # 测试3：复杂任务，多步推理
    run_react_agent("把我所有情绪相关的笔记整合成一段话，帮我分析近期状态")