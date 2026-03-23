"""
tests/eval_prompt_result.py - Prompt A/B 测试 v4

v4 修正：
  1. 澄清判断不再依赖问号，改为"无工具调用 + 有回复内容 + 澄清关键词"三重判断
  2. 每个用例重复运行 N 次（默认 3），取多数结果，消除 LLM 随机性干扰
  3. temperature 固定为 0，提升可复现性
  4. 修正 normal_search_topic 预期值：该输入无明确关键词，应触发澄清而非检索
  5. 补充 forbidden 场景，覆盖更多 get_note_stats 误触情况
"""

import json
import os
from collections import Counter

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

# ══════════════════════════════════════════════════════════════
# Part 1: 两个待对比的 Prompt
# ══════════════════════════════════════════════════════════════
PROMPT_A = """你叫 Rover，是用户的长期私人笔记助手和第二大脑。
你的所有回答必须以用户自己的笔记为基础，绝不编造未经检索的内容。

## 行为原则

1. 任何涉及笔记内容的回答，必须先调用工具，不得凭记忆编造。
2. get_note_stats 仅在用户明确询问统计数据时调用，
   不得在检索或审阅流程中主动触发。
3. 没有明确目标的笔记请求，不调用工具。
   明确目标 = 包含笔记标题、note_id、或具体关键词之一。

## 回答风格

- 语气温暖，像一个了解你的老朋友
- 引用笔记时带上标题和创建日期，方便用户定位
- 纠错时用"这个说法在当前已更新为..."，而不是"你写错了"
- 长度以够用为准，不为凑字数展开"""


PROMPT_B = """你叫 Rover，是用户的长期私人笔记助手和第二大脑。
你的所有回答必须以用户自己的笔记为基础，绝不编造未经检索的内容。

## 行为原则

1. 任何涉及笔记内容的回答，必须先调用工具，不得凭记忆编造。
2. get_note_stats 仅在用户明确询问统计数据时调用，
   不得在检索或审阅流程中主动触发。
3. 没有明确目标的笔记请求，不调用工具。
   明确目标 = 包含笔记标题、note_id、或具体关键词之一。
   ✗ 不该调工具："审阅笔记""检查一下""帮我看看笔记"（没有指定目标）
   ✓ 应该调工具："审阅 note_id=75""检查《LangChain笔记》""找关于焦虑的笔记"

## 回答风格

- 语气温暖，像一个了解你的老朋友
- 引用笔记时带上标题和创建日期，方便用户定位
- 纠错时用"这个说法在当前已更新为..."，而不是"你写错了"
- 长度以够用为准，不为凑字数展开"""


# ══════════════════════════════════════════════════════════════
# Part 2: Mock 工具定义
# ══════════════════════════════════════════════════════════════
MOCK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": (
                "用自然语言语义检索用户的笔记，返回片段预览和基本信息。"
                "适用：一切需要找笔记的场景，包括模糊查找、主题回顾、跨笔记分析。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "返回条数，默认8"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_note",
            "description": (
                "按 ID 读取单篇笔记的完整原文。"
                "仅在 search_notes 已找到目标、且确实需要完整内容时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "笔记唯一ID"},
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_note_stats",
            "description": (
                "返回笔记总数、最近更新时间、本月篇数。"
                "仅在用户明确询问统计数据时调用，不得在检索或审阅流程中主动触发。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ══════════════════════════════════════════════════════════════
# Part 3: 澄清判断
# ══════════════════════════════════════════════════════════════
# v3 的问题：只靠问号判断，模型用句号结尾的澄清句会被误判为失败
# v4 修正：无工具调用 + 有回复内容 + 命中澄清关键词，三重判断
_CLARIFY_KEYWORDS = [
    "哪篇", "哪一篇", "具体", "您是指", "你是指",
    "是指", "哪个", "告诉我", "能说说", "可以告诉",
    "什么笔记", "哪篇笔记", "指定", "确认一下",
]

def is_clarify_response(called_tools: list, content: str) -> bool:
    """判断模型是否在请求澄清（而非调工具或瞎答）"""
    if called_tools:
        return False
    if not content:
        return False
    return any(kw in content for kw in _CLARIFY_KEYWORDS)


# ══════════════════════════════════════════════════════════════
# Part 4: 测试用例
# ══════════════════════════════════════════════════════════════
# v4 修正说明：
#
# 1. normal_search_topic "我最近在关注什么话题"
#    → 无明确关键词，按 Prompt 原则应澄清，修正 category 为 ambiguous
#
# 2. 新增 forbidden 场景，覆盖更容易触发 get_note_stats 误触的输入：
#    "总结一下我所有笔记" / "最近写了什么" / "帮我回顾一下我的笔记"

TEST_CASES = [
    # ── 正常场景 ────────────────────────────────────────────────
    {
        "id": "normal_search_keyword",
        "input": "找找我写过关于焦虑的笔记",
        "expected_tools": ["search_notes"],
        "expected_behavior": None,
        "category": "normal",
    },
    {
        "id": "normal_review_with_id",
        "input": "检查一下 note_id=75 这篇笔记，有错吗",
        "expected_tools": ["get_note"],
        "expected_behavior": None,
        "category": "normal",
    },
    {
        "id": "normal_review_with_title",
        "input": "帮我检查一下《LangChain 学习笔记》这篇有没有错",
        "expected_tools": ["search_notes"],
        "expected_behavior": None,
        "category": "normal",
    },
    {
        "id": "normal_stats_count",
        "input": "我这个月写了几篇笔记",
        "expected_tools": ["get_note_stats"],
        "expected_behavior": None,
        "category": "normal",
    },
    {
        "id": "normal_stats_total",
        "input": "我总共写了多少笔记",
        "expected_tools": ["get_note_stats"],
        "expected_behavior": None,
        "category": "normal",
    },

    # ── 模糊场景（应触发澄清，不调工具）────────────────────────
    {
        "id": "ambiguous_review_no_target",
        "input": "检查我的笔记，有错吗",
        "expected_tools": [],
        "expected_behavior": "clarify",
        "category": "ambiguous",
    },
    {
        "id": "ambiguous_check_no_target",
        # 触发过 20 次工具调用的线上真实 case，保留为回归用例
        "input": "检查一下我的笔记有没有错误",
        "expected_tools": [],
        "expected_behavior": "clarify",
        "category": "ambiguous",
    },
    {
        "id": "ambiguous_help_vague",
        "input": "帮我看看笔记",
        "expected_tools": [],
        "expected_behavior": "clarify",
        "category": "ambiguous",
    },
    {
        "id": "ambiguous_check_short",
        "input": "纠错一下",
        "expected_tools": [],
        "expected_behavior": "clarify",
        "category": "ambiguous",
    },
    {
        # v4 新增：原来在 normal 里但预期错误，无关键词应澄清
        "id": "ambiguous_recent_topic",
        "input": "我最近在关注什么话题",
        "expected_tools": [],
        "expected_behavior": "clarify",
        "category": "ambiguous",
    },

    # ── 禁止场景（不得误触 get_note_stats）──────────────────────
    {
        "id": "forbidden_stats_in_search",
        "input": "找找我写过的 LangChain 相关笔记",
        "expected_tools": ["search_notes"],
        "expected_behavior": None,
        "forbidden_tools": ["get_note_stats"],
        "category": "forbidden",
    },
    {
        "id": "forbidden_stats_in_review",
        "input": "帮我审阅 note_id=58 这篇",
        "expected_tools": ["get_note"],
        "expected_behavior": None,
        "forbidden_tools": ["get_note_stats"],
        "category": "forbidden",
    },
    {
        # v4 新增：总结所有笔记容易错误触发 get_note_stats
        "id": "forbidden_stats_in_summary",
        "input": "总结一下我所有的笔记",
        "expected_tools": ["search_notes"],
        "expected_behavior": None,
        "forbidden_tools": ["get_note_stats"],
        "category": "forbidden",
    },
    {
        # v4 新增："最近写了什么"有时会被误判为统计需求
        "id": "forbidden_stats_in_recent",
        "input": "我最近写了什么",
        "expected_tools": ["search_notes"],
        "expected_behavior": None,
        "forbidden_tools": ["get_note_stats"],
        "category": "forbidden",
    },
    {
        # v4 新增："回顾笔记"无明确关键词，应澄清，不应触发 get_note_stats
        "id": "forbidden_stats_in_review_vague",
        "input": "帮我回顾一下我的笔记",
        "expected_tools": [],
        "expected_behavior": "clarify",
        "forbidden_tools": ["get_note_stats"],
        "category": "forbidden",
    },
]


# ══════════════════════════════════════════════════════════════
# Part 5: 执行单条测试用例（单次）
# ══════════════════════════════════════════════════════════════
def run_once(model, prompt: str, user_input: str) -> dict:
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=user_input),
    ]
    response = model.invoke(messages)
    tool_calls = getattr(response, "tool_calls", []) or []
    called_tools = [tc["name"] for tc in tool_calls]
    content = response.content or ""

    return {
        "called_tools": called_tools,
        "is_clarify": is_clarify_response(called_tools, content),
        "response_preview": content[:120],
    }


# ══════════════════════════════════════════════════════════════
# Part 6: 重复运行取多数，消除随机性
# ══════════════════════════════════════════════════════════════
# v4 新增：每个用例重复 REPEAT 次，called_tools 取出现最多的那次结果
# temperature=0 时理论上结果稳定，REPEAT=3 作为保险

REPEAT = 3

def run_single_case(model, prompt: str, user_input: str) -> dict:
    runs = [run_once(model, prompt, user_input) for _ in range(REPEAT)]

    # 用 called_tools 的字符串化结果做多数投票
    votes = Counter(json.dumps(r["called_tools"], ensure_ascii=False) for r in runs)
    majority_tools_str, _ = votes.most_common(1)[0]
    majority_tools = json.loads(majority_tools_str)

    # 找到与多数结果一致的第一次运行，取其 is_clarify 和 preview
    representative = next(
        r for r in runs
        if r["called_tools"] == majority_tools
    )

    return {
        "called_tools": majority_tools,
        "is_clarify": representative["is_clarify"],
        "response_preview": representative["response_preview"],
        "all_runs": [r["called_tools"] for r in runs],  # 保留原始数据供调试
    }


# ══════════════════════════════════════════════════════════════
# Part 7: 跑全部用例，计算指标
# ══════════════════════════════════════════════════════════════
def evaluate(prompt: str, prompt_name: str, model) -> dict:
    results = []

    for case in TEST_CASES:
        print(f"    [{prompt_name}] {case['id']} × {REPEAT}次...")
        result = run_single_case(model, prompt, case["input"])

        called = result["called_tools"]
        expected_tools = case["expected_tools"]
        expected_behavior = case.get("expected_behavior")
        forbidden = case.get("forbidden_tools", [])

        if expected_behavior == "clarify":
            tool_match = (called == [] and result["is_clarify"])
        else:
            tool_match = set(called) == set(expected_tools)

        forbidden_triggered = any(t in called for t in forbidden)

        results.append({
            "id": case["id"],
            "category": case["category"],
            "input": case["input"],
            "expected_tools": expected_tools,
            "expected_behavior": expected_behavior,
            "actual_tools": called,
            "all_runs": result["all_runs"],
            "is_clarify": result["is_clarify"],
            "tool_match": tool_match,
            "forbidden_triggered": forbidden_triggered,
            "tool_count": len(called),
            "response_preview": result["response_preview"],
        })

    total = len(results)
    accuracy = sum(1 for r in results if r["tool_match"]) / total
    avg_tool_count = sum(r["tool_count"] for r in results) / total
    forbidden_rate = sum(1 for r in results if r["forbidden_triggered"]) / total

    ambiguous = [r for r in results if r["category"] == "ambiguous"]
    clarify_rate = (
        sum(1 for r in ambiguous if r["is_clarify"] and r["actual_tools"] == [])
        / len(ambiguous)
        if ambiguous else 0
    )

    # 按分类统计准确率，方便定位薄弱环节
    category_accuracy = {}
    for cat in ["normal", "ambiguous", "forbidden"]:
        cat_results = [r for r in results if r["category"] == cat]
        if cat_results:
            category_accuracy[cat] = sum(1 for r in cat_results if r["tool_match"]) / len(cat_results)

    return {
        "prompt_name": prompt_name,
        "metrics": {
            "工具调用准确率（总体）":      f"{accuracy:.0%}",
            "工具调用准确率（normal）":    f"{category_accuracy.get('normal', 0):.0%}",
            "工具调用准确率（ambiguous）": f"{category_accuracy.get('ambiguous', 0):.0%}",
            "工具调用准确率（forbidden）": f"{category_accuracy.get('forbidden', 0):.0%}",
            "澄清触发率（模糊场景）":      f"{clarify_rate:.0%}",
            "get_note_stats 误触率":      f"{forbidden_rate:.0%}",
            "平均工具调用次数":            f"{avg_tool_count:.1f}",
        },
        "details": results,
    }


# ══════════════════════════════════════════════════════════════
# Part 8: 输出报告
# ══════════════════════════════════════════════════════════════
def print_report(result_a: dict, result_b: dict):
    print("\n" + "=" * 65)
    print("📊 Prompt A/B 测试报告")
    print("=" * 65)

    metrics_a = result_a["metrics"]
    metrics_b = result_b["metrics"]
    print(f"\n{'指标':<30} {'Prompt A':>12} {'Prompt B':>12}")
    print("-" * 55)
    for k in metrics_a:
        print(f"{k:<30} {metrics_a[k]:>12} {metrics_b[k]:>12}")

    details_a = {r["id"]: r for r in result_a["details"]}
    details_b = {r["id"]: r for r in result_b["details"]}

    print("\n\n📋 所有用例结果")
    print("-" * 65)
    for case in TEST_CASES:
        da = details_a[case["id"]]
        db = details_b[case["id"]]
        a_mark = "✅" if da["tool_match"] else "❌"
        b_mark = "✅" if db["tool_match"] else "❌"
        print(f"\n[{da['category']}] {case['id']}")
        print(f"  输入:      {da['input']}")
        print(f"  预期:      tools={da['expected_tools']} behavior={da['expected_behavior']}")
        print(f"  Prompt A: 工具={da['actual_tools']} 澄清={da['is_clarify']} 多轮={da['all_runs']} {a_mark}")
        print(f"  Prompt B: 工具={db['actual_tools']} 澄清={db['is_clarify']} 多轮={db['all_runs']} {b_mark}")

    print("\n\n⚠️  共同失败用例")
    print("-" * 65)
    both_wrong = [
        da for da in result_a["details"]
        if not da["tool_match"] and not details_b[da["id"]]["tool_match"]
    ]
    if both_wrong:
        for da in both_wrong:
            db = details_b[da["id"]]
            print(f"\n  {da['id']}: {da['input']}")
            print(f"    预期: tools={da['expected_tools']} behavior={da['expected_behavior']}")
            print(f"    A:   tools={da['actual_tools']} clarify={da['is_clarify']} 多轮={da['all_runs']}")
            print(f"    B:   tools={db['actual_tools']} clarify={db['is_clarify']} 多轮={db['all_runs']}")
    else:
        print("  没有共同失败的用例。")

    print("\n" + "=" * 65)


# ══════════════════════════════════════════════════════════════
# Part 9: 入口
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    model = ChatOpenAI(
        model=os.getenv("MIMO_MODEL"),
        api_key=os.getenv("MIMO_API_KEY"),
        base_url=os.getenv("MIMO_BASE_URL"),
        temperature=0,   # 固定为 0，提升可复现性
    ).bind_tools(MOCK_TOOLS)

    print("🧪 正在运行 Prompt A...")
    result_a = evaluate(PROMPT_A, "Prompt A", model)

    print("🧪 正在运行 Prompt B...")
    result_b = evaluate(PROMPT_B, "Prompt B", model)

    print_report(result_a, result_b)

    with open("eval_prompt_result.json", "w", encoding="utf-8") as f:
        json.dump(
            {"prompt_a": result_a, "prompt_b": result_b},
            f, ensure_ascii=False, indent=2,
        )
    print("📁 完整结果已保存到 eval_prompt_result.json")