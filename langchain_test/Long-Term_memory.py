from langgraph.store.memory import InMemoryStore
from embeddings import Embeddings


# 使用嵌入索引初始化存储
store = InMemoryStore(index={"embed": Embeddings, "dims": 2})

# 定义明明空间
user_id = "user"
application_context = "chitchat"
namespace = (user_id,application_context)

# 存储一个记忆项
store.put(
    namespace,
    "memory-1",
    {
        "rules":[
            "用户只说中文",
            "用户喜欢简洁准确的回答"
        ],
        "my-key":"my-value"
    }
)

# 记忆检索
item = store.get(namespace,"memory-1")
print(item)

# 使用过滤器查询
items = store.search(
    namespace,
    filter={
        "my-key":"my-value"
    },
    query="语言喜好"
)
print(items)