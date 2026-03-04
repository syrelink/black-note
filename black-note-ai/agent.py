import os
import pymysql
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

load_dotenv()

# ── 数据库配置（建议后续使用连接池或环境变量加密密码） ────────────────
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",          # 生产环境千万不要硬编码！建议用 secrets manager
    "database": "black_note",
    "charset": "utf8mb4",
}

# 全局变量，由 main.py 或 FastAPI 初始化时注入
# （这样不同用户请求可以共享 vectorstore，但 user_id 要动态传入）
_vectorstore = None
_user_id = None


def init_agent_context(vectorstore, user_id: str):
    """
    初始化 Agent 上下文（通常在 FastAPI 的依赖注入或 startup 事件中调用）
    :param vectorstore: Chroma 或其他向量存储实例
    :param user_id: 当前用户的唯一标识，用于过滤笔记
    """
    global _vectorstore, _user_id
    _vectorstore = vectorstore
    _user_id = user_id


@tool
def search_notes(query: str) -> str:
    """
    工具1：语义搜索用户的笔记
    使用场景：当用户问“关于XXX的笔记有哪些？”或需要查找相关主题时调用
    返回：匹配的笔记列表（ID + 标题 + 简短摘要），带相似度过滤
    """
    if _vectorstore is None or _user_id is None:
        return "系统未初始化，无法搜索笔记"

    # 使用向量相似度搜索，并按 user_id 过滤（确保只搜当前用户笔记）
    docs = _vectorstore.similarity_search_with_score(
        query,
        k=5,
        filter={"user_id": _user_id}  # 重要：防止跨用户数据泄露
    )

    if not docs:
        return "未找到相关笔记"

    results = []
    for doc, score in docs:
        similarity = 1 - score  # score 越小越相似，转成 0~1 的相似度
        if similarity >= 0.3:   # 阈值可调，0.3 ≈ 比较相关的结果
            results.append(
                f"- ID: {doc.metadata.get('note_id', '未知')} "
                f"标题: {doc.metadata.get('title', '无标题')} "
                f"摘要: {doc.page_content[:60]}..."
            )

    return "\n".join(results) if results else "未找到足够相关的笔记（相似度过低）"


@tool
def get_note_detail(note_id: str) -> str:
    """
    工具2：根据笔记 ID 获取完整笔记内容
    使用场景：Agent 搜索后决定要看某篇笔记详情时调用
    返回：标题 + 创建时间 + 完整内容
    """
    if _user_id is None:
        return "系统未初始化，无法获取笔记"

    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 防止越权：必须同时校验 user_id 和 is_deleted=0
            cursor.execute(
                """
                SELECT title, content, created_at 
                FROM note 
                WHERE id = %s AND user_id = %s AND is_deleted = 0
                """,
                (note_id, _user_id)
            )
            note = cursor.fetchone()

        conn.close()

        if not note:
            return f"笔记 {note_id} 不存在或已被删除/无权限"

        return (
            f"标题：{note['title']}\n"
            f"创建时间：{note['created_at']}\n"
            f"内容：\n{note['content']}"
        )

    except Exception as e:
        return f"数据库查询失败：{str(e)}"


def build_agent():
    """
    创建 ReAct 风格的 Agent
    ReAct 流程：Reason（思考） → Act（调用工具） → Observe（看工具结果） → 循环直到能直接回答

    当前实现：
    1. LLM 使用 DeepSeek（或你配置的其他模型）
    2. 绑定两个工具：search_notes + get_note_detail
    3. 通过 system prompt 告诉 Agent 如何使用工具和行为准则
    """
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,           # 较低温度 → 更稳定、少胡说
        streaming=True,          # 如果 FastAPI 需要流式返回，可打开
    )

    # 系统提示词（非常重要！决定了 Agent 的性格和工具使用方式）
    system_prompt = (
        "你是用户的私人笔记助手，专门帮助用户搜索、阅读和管理自己的笔记。\n"
        "你有以下工具可用：\n"
        "1. search_notes：用于查找相关笔记列表（输入关键词或问题描述）\n"
        "2. get_note_detail：用于读取某篇笔记的完整内容（必须先通过 search_notes 拿到 ID）\n\n"
        "处理用户问题的标准流程：\n"
        "1. 先理解用户意图\n"
        "2. 如果需要查找笔记 → 调用 search_notes\n"
        "3. 如果搜索结果中有合适的笔记 ID，且需要详情 → 调用 get_note_detail\n"
        "4. 综合工具返回的信息，给出准确、自然的回答\n"
        "5. 绝对不要编造笔记中不存在的内容！如果信息不足，就诚实地说找不到。\n"
        "6. 回答要简洁、有条理，使用中文。"
    )


    agent = create_agent(
        model=llm,
        tools=[search_notes, get_note_detail],
        system_prompt=system_prompt,  # 参数名从prompt改成system_prompt
    )

    return agent