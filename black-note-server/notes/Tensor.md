## Tensor基础用法

### 1. Tensor 的创建

#### 1.1 tensor
```python
import torch

# 直接创建
t = torch.tensor([[1, 2], [3, 4]])  # dtype自动推断为int64
t_float = torch.tensor([[1.0, 2], [3, 4]], dtype=torch.float32)  # 指定dtype
```

#### 1.2 zeros、ones
```python
zeros = torch.zeros(2, 3)  # 2行3列的全零Tensor（dtype=float32）
ones = torch.ones(2, 3)    # 全一Tensor 
```

#### 1.3 rand、randn、randint
```python
rand = torch.rand(2, 3)    # 均匀分布 [0, 1)
randn = torch.randn(2, 3)  # 标准正态分布（均值0，方差1）
rand_int = torch.randint(0, 10, (2, 3))  # 0~10的随机整数
```

#### 1.4 from_numpy
```python
import numpy as np
a_np = np.array([[1, 2], [3, 4]])
t = torch.from_numpy(a_np)  # 共享内存（修改a_np会影响t）
```

---

### 2. 形状操作
#### 2.1 reshape、view、flatten

```python
t = torch.rand(2, 3)
reshaped = t.reshape(3, 2)  # 调整形状（不复制数据）
viewed = t.view(3, 2)       # view()方法调整tensor的形状，但是必须得保证调整前后元素个数一致
a = t.view(-1,1)            # -1会自动计算大小，view方法返回的tensor和原tensor共享内存，修改一个，另外一个也会修改
flattened = t.flatten()     # 展平为一维Tensor
```

#### 2.2 transpose、permute
```python
a = t.transpose(0, 1)    # 交换第0维和第1维（行列转s置）
b = t.permute(1, 0)      # 更灵活的维度交换
```

#### 2.3 **squeeze、**unsqueez
```python
t = torch.rand(2, 1, 3)
squeezed = t.squeeze(dim=1)  # 压缩第1维的“1”，某一维度为“1”才能压缩，如果第1维的维度是“5”如(2,5,3)则无法亚索第1维
unsqueezed = t.unsqueeze(0)  # 在第0维增加维度（形状变为[1, 2, 1, 3]）
```

#### 2.4 range

```python
torch.arange(start=0, end, step=1, *, dtype=None, device=None) # 生成一个包含等差数列的一维张量（Tensor），范围由 start 到 end（不包含 end），步长为 step。
```



---

### 3. Tensor数据类型

| 数据类型                   | CPU tensor         | GPU tensor              |
| :------------------------- | :----------------- | :---------------------- |
| 32bit浮点                  | torch.FloatTensor  | torch.cuda.FloatTensor  |
| 64bit浮点                  | torch.DoubleTensor | torch.cuda.DoubleTensor |
| 16bit半精度浮点            | torch.HalfTensor   | torch.cuda.HalfTensor   |
| 8bit无符号整型（0~255）    | torch.ByteTensor   | torch.cuda.ByteTensor   |
| 8bit有符号整型（-128~127） | torch.CharTensor   | torch.cuda.CharTensor   |
| 16bit有符号整型            | torch.ShortTensor  | torch.cuda.ShortTensor  |
| 32bit有符号整型            | torch.IntTensor    | torch.cuda.IntTensor    |
| 64bit有符号整型            | torch.LongTensor   | torch.cuda.LongTensor   |

### 4. 数学运算

#### 4.1 **逐元素运算**
```python
# 创建一个张量
x = torch.tensor([-2.0, -1.0, 0.0, 1.0, 2.0])

# 对张量的每个元素应用指数函数
y = torch.exp(x)
print(y)
'''
torch.exp 函数是一个非常基础且常用的函数，它用于计算输入张量（Tensor）的每个元素的指数。指数函数是数学中的一个基本函数，通常表示为 e^x，其中 e 是自然对数的底数，约等于 2.71828。
'''

a = torch.tensor([1, 2])
b = torch.tensor([3, 4])

c_add = a + b      # 加法 [4, 6]
c_mul = a * b      # 乘法 [3, 8]
c_pow = a ** 2     # 平方 [1, 4]
c_exp = torch.exp(a)  # 指数运算 [e^1, e^2]
```

#### 4.2 **矩阵乘法**
```python
a = torch.rand(2, 3)
b = torch.rand(3, 2)
c = torch.matmul(a, b)  # 或简写为 a @ b
```

#### 4.3 点积与范数
```python
dot_product = torch.dot(a, b)         # 向量内积
cos_sim = torch.cosine_similarity(a, b, dim=0)  # 余弦相似度
norm = torch.norm(a)                  # L2范数
```

---

### 5. 聚合函数
#### 5.1 **求和/均值/最大值/最小值**
```python
t = torch.tensor([[1, 2], [3, 4]])

sum_all = t.sum()           # 10（所有元素和）
sum_dim0 = t.sum(dim=0)     # 沿第0维求和 [4, 6]
mean = t.mean()             # 2.5
max_val, max_idx = t.max(dim=1)  # 最大值及索引（dim=1）
min_val = t.min()           # 1
```

#### 5.2 **逻辑运算**
```python
mask = t > 2                # 生成布尔Tensor
selected = t[mask]          # 筛选大于2的元素 [3, 4]
```

---

### 6. 自动求导（Autograd）
PyTorch 的 **自动求导（Autograd）** 是神经网络训练的核心机制，它允许框架自动计算梯度（导数），无需手动推导数学公式。

---

#### 6.1 自动求导的核心概念
1. **`requires_grad=True`**
   当创建 Tensor 时设置 `requires_grad=True`，PyTorch 会跟踪该 Tensor 的所有操作，构建计算图（Computation Graph），以便后续自动求导。
   ```python
   x = torch.tensor(2.0, requires_grad=True)  # 标记需要计算梯度
   ```

2. **计算图（Computation Graph）**
   PyTorch 会记录所有与 `x` 相关的运算，形成一个动态的计算图。例如：
   
   ```python
   y = x ** 2 + 3 * x  # y = x² + 3x
   ```
   计算图会记录 `y` 如何从 `x` 计算得到。
   
3. **`backward()` 方法**
   调用 `y.backward()` 时，PyTorch 会从 `y` 反向传播（Backpropagate）计算梯度，并将结果存储在 `x.grad` 中。

---

#### 6.2 基本用法示例
示例 1：简单标量求导

```python
# 1. 定义需要梯度的Tensor，注意tensor需要浮点类型
x = torch.tensor(2.0, requires_grad=True)

# 2. 前向计算（构建计算图）
y = x ** 2 + 3 * x  # y = x² + 3x

# 3. 反向传播计算梯度
y.backward()  # 自动计算 dy/dx

# 4. 查看梯度
print(x.grad)  # 输出：7.0 (因为 dy/dx = 2x + 3 = 2*2 + 3 = 7)
```

示例 2：多变量求导

```python
# 定义两个需要梯度的Tensor
a = torch.tensor(1.0, requires_grad=True)
b = torch.tensor(2.0, requires_grad=True)

# 前向计算
c = a * b + a ** 2  # c = ab + a²

# 反向传播
c.backward()

# 查看梯度
print(a.grad)  # dc/da = b + 2a = 2 + 2*1 = 4
print(b.grad)  # dc/db = a = 1
```

---

#### 6.3 神经网络中的典型用法
在训练神经网络时，自动求导用于计算损失函数对模型参数的梯度，进而更新参数。

**关键问题：为什么要求导？**

**1. 梯度指示了参数调整的方向**

梯度$ \frac{\partial loss}{\partial w}$ 和 $\frac{∂loss}{∂b}$ 告诉我们：

- **如何调整参数才能使 Loss 减小**。
- 例如，当 `w.grad = -28.0` 时，说明增加 `w` 的值会减少 Loss（因为梯度为负）。

**2. 梯度下降的直观解释**

假设你站在山顶（初始参数值），目标是找到山谷最低点（最小 Loss）。

- **梯度方向**：最陡峭的**下山方向**（负梯度方向）。
- **梯度大小**：山坡的陡峭程度（调整参数的步长）。

```python
# 训练一个简单线性回归模型
import torch

# 1. 定义模型和数据
X = torch.tensor([[1.0], [2.0], [3.0]])  # 输入特征
y = torch.tensor([[2.0], [4.0], [6.0]])  # 真实标签

# 模型参数（权重和偏置）
w = torch.tensor(0.0, requires_grad=True)  # 权重
b = torch.tensor(0.0, requires_grad=True)  # 偏置

# 2. 前向传播
def forward(X):
    return X * w + b  # 线性模型：y_pred = Xw + b

# 3. 定义损失函数（均方误差）
loss = torch.mean((forward(X) - y) ** 2)

# 4. 反向传播计算梯度
loss.backward()

# 5. 查看梯度
print("梯度 w.grad:", w.grad)  # 损失对w的梯度
print("梯度 b.grad:", b.grad)  # 损失对b的梯度

# 6. 手动更新参数（通常使用优化器如 SGD）
learning_rate = 0.01
with torch.no_grad():  # 关闭梯度跟踪，避免更新操作被记录
    w -= learning_rate * w.grad
    b -= learning_rate * b.grad

# 7. 清零梯度（防止累积,重要！）
w.grad.zero_()
b.grad.zero_()

# 8. 验证更新后的 Loss
y_pred_new = w * X + b
loss_new = torch.mean((y_pred_new - y) ** 2)

print("更新后 Loss:", loss_new.item())  # 输出：21.28（比初始 Loss 28.0 减小了！）

```

---

#### 6.4 关键注意事项
1. **梯度清零**
   每次反向传播前需调用 `grad.zero_()` 清除之前的梯度，否则梯度会累积：
   
   ```python
   # 错误用法：梯度未清零
   for _ in range(10):
       y = x * 2
       y.backward()
       print(x.grad)  # 梯度会累积为 2, 4, 6, ..., 20
   
   # 正确用法
   x.grad.zero_()    # 清零梯度
   y = x * 2
   y.backward()
   ```
   
2. **`with torch.no_grad()`**
   在更新参数或推理时，使用 `with torch.no_grad()` 临时禁用梯度跟踪，避免不必要的计算：
   
   ```python
   with torch.no_grad():
       w -= learning_rate * w.grad  # 更新操作不会影响计算图
   ```
   
3. **非标量反向传播**
   当 `y` 是向量时（如多输出任务），需传入 `gradient` 参数：
   ```python
   y = torch.tensor([1.0, 2.0], requires_grad=True)
   z = y.sum()       # 先将向量转换为标量
   z.backward()      # 此时 y.grad = [1.0, 1.0]
   ```

---

#### 6.5 常见问题
1. 为什么PyTorch 的 **自动求导（Autograd）** 是神经网络训练的核心机制，它允许框架自动计算梯度（导数），无需手动推导数学公式。以下是详细解释和一般用法：

### 7. 设备管理（CPU/GPU）

#### 7.1 将Tensor移动到GPU
```python
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
t_gpu = t.to(device)        # 移动Tensor到GPU
```

#### 7.2 **检查设备信息**
```python
print(t.device)             # 输出设备（cpu或cuda:0）
```

### 8. 其他常用操作
#### 8.1 **拼接与分割**
```python
t1 = torch.tensor([[1, 2]]) #1*2
t2 = torch.tensor([[3, 4]]) #1*2

# 拼接
cat = torch.cat([t1, t2], dim=0)  # 沿行拼接 → [[1,2], [3,4]] 
stack = torch.stack([t1, t2])     # 新增维度拼接 → shape [2,1,2]

# 分割
chunks = torch.chunk(t, 2, dim=1) # 沿dim=1分割为2块
```

#### 8.2 **索引与切片**
```python
t = torch.tensor([[1, 2], [3, 4]])

row = t[0, :]     # 第一行 → [1, 2]
col = t[:, 0]     # 第一列 → [1, 3]
sub_tensor = t[0:2, 1]  # 切片 → [2, 4]
```

#### 8.3 **广播机制**
```python
a = torch.tensor([[1], [2], [3]])  # shape [3,1]
b = torch.tensor([4, 5, 6])        # shape [3]
c = a + b  # a扩展为[3,3], b扩展为[3,3], 结果shape [3,3]
```

---

### 9. 保存与加载
```python
# 保存Tensor
torch.save(t, 'tensor.pt')

# 加载Tensor
t_loaded = torch.load('tensor.pt')
```

---

### 10. 常见激活函数
```python
t = torch.tensor([-1.0, 2.0])

relu = torch.relu(t)       # [0.0, 2.0]
sigmoid = torch.sigmoid(t) # [0.2689, 0.8808]
tanh = torch.tanh(t)       # [-0.7616, 0.9640]
```

### tips

大多数`torch.function`都有一个参数out，可以将其产生的结果保存在out指定的tensor之中

```python
b = torch.tensor()
torch.randn(2, 3, out=b)
print(b)
```





## Pytorch 的 nn 工具箱

### 前言

**卷积核如何自动学习？**

在训练过程中，**反向传播和梯度下降会自动优化卷积核的权重**：

1. **前向传播**：卷积核在图像上滑动，生成特征图。
2. **计算损失**：比较预测结果与真实标签的差异。
3. **反向传播**：根据损失计算卷积核权重的梯度。
4. **更新权重**：沿梯度方向调整卷积核的值，使其更擅长检测对任务有用的特征。

**示例：自动学习边缘检测**

- 初始时，卷积核是随机初始化的，可能无法检测任何有效特征。
- 经过训练后，某些卷积核的权重会逐渐趋近于边缘检测模式（如垂直或水平边缘）。

------

**卷积核学到了什么？**

通过可视化卷积核的激活，可以直观理解其功能：

- 第一层卷积核：通常学习到边缘、颜色、纹理检测器。
- 深层卷积核：响应更复杂的模式（如车轮、动物眼睛等）。

```python
import torch.nn as nn

# 定义一个卷积层：输入3通道（RGB），输出64通道，3x3卷积核
conv_layer = nn.Conv2d(
    in_channels=3,    # 输入通道数（如RGB图像）
    out_channels=64,  # 输出通道数（即64种卷积核）
    kernel_size=3,    # 卷积核大小3x3
    stride=1,         # 滑动步长
    padding=1         # 边缘填充（保持输出尺寸）
)

# 查看卷积核权重（随机初始化）
print(conv_layer.weight.shape)  # 输出：[64, 3, 3, 3]

'''总结
CNN通过卷积核的局部感知和参数共享机制，能够高效提取图像的层次化特征。卷积核的设计和优化是模型性能的关键，其核心思想是让网络自动学习对任务最有用的特征模式。实际应用中，结合经典架构和正则化技巧，可以充分发挥CNN的特征提取能力。
'''
```

