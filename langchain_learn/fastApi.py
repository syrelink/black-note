from fastapi import FastAPI

app = FastAPI()  # 创建应用实例

@app.get("/")  # 定义 GET 路由，路径是根 "/"
def read_root():
    return {"Hello": "World"}  # 返回 JSON 响应

@app.get("/items/{item_id}")
def read_item(item_id: int):  # 类型提示：item_id 必须是 int
    return {"item_id": item_id}

@app.get("/items")
def read_items(skip: int = 0, limit: int = 10):  # 默认值
    return {"skip": skip, "limit": limit}

from pydantic import BaseModel

class Item(BaseModel):  # 定义模型
    name: str
    price: float
    is_offer: bool = None  # 可选字段

@app.post("/items")
def create_item(item: Item):  # item 来自请求体
    return item

from fastapi import Response

class ItemResponse(BaseModel):
    name: str
    price: float

@app.post("/items", response_model=ItemResponse, status_code=201)
def create_item(item: Item):
    # 模拟保存
    return item  # 只返回 name 和 price，忽略 is_offer