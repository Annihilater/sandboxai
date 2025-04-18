# MentisSandbox 测试指南

本文档提供了如何使用 `test_sandbox.sh` 脚本对 MentisSandbox 进行全面测试的指南。该测试脚本涵盖了从基础功能到高级特性的各个方面，确保沙盒环境正常工作。

## 准备工作

在开始测试前，请确保：

1. MentisRuntime 服务已经启动
   ```bash
   # 在项目根目录下
   go run ./mentisruntime/main.go
   ```

2. 已构建最新的沙盒镜像
   ```bash
   make build-box-image
   ```

3. 已创建一个沙盒实例，并获取其 ID
   ```bash
   curl -X POST http://127.0.0.1:5266/sandboxes
   # 将返回如: {"sandbox_id":"752db9c2-0951-4b2c-a415-c2c8b6452cb2"}
   ```

## 运行测试

测试过程分为两部分：WebSocket 监控和测试执行。

### 第 1 步：启动 WebSocket 监控

在一个终端窗口中，连接到沙盒的 WebSocket 流以实时监控测试结果：

```bash
websocat ws://127.0.0.1:5266/sandboxes/YOUR_SANDBOX_ID/stream
```

替换 `YOUR_SANDBOX_ID` 为您实际的沙盒 ID。

### 第 2 步：执行测试脚本

在另一个终端窗口中，执行测试脚本：

```bash
chmod +x test_sandbox.sh
./test_sandbox.sh
```

当提示时，输入您的沙盒 ID。脚本将按顺序运行所有测试用例。

## 测试用例说明

测试脚本包含 30 个测试用例，覆盖以下功能领域：

### 1. 基础功能测试 (测试 1-4)

- **Shell 命令执行**：验证基本的 Shell 命令是否正常工作
- **IPython 执行**：验证基本的 Python 代码执行
- **命令行参数**：测试带参数的命令执行
- **多行代码**：测试多行 Python 代码执行

**预期结果：** 
- 所有命令应返回退出码 0
- WebSocket 流应显示正确的输出文本

### 2. 状态持久性测试 (测试 5-8)

- **变量设置**：测试在 IPython 中设置变量
- **变量读取**：验证先前设置的变量可以被读取
- **变量修改**：测试变量值的修改
- **变量状态确认**：确认变量修改已保存

**预期结果：**
- 变量 `test_var_5` 成功设置为 123
- 后续测试中可以访问和修改该变量
- 变量值应该成功增加到 124

### 3. 库和计算测试 (测试 9-12)

- **NumPy 基础**：测试 NumPy 导入和基本数组操作
- **NumPy 计算**：测试矩阵计算功能
- **标准库 (datetime)**：验证 datetime 库的使用
- **标准库 (json)**：验证 JSON 序列化功能

**预期结果：**
- NumPy 应成功导入并执行计算
- 标准库应正常工作并返回预期结果

### 4. 文件系统操作 (测试 13-18)

- **创建文件**：使用 Shell 命令创建文件
- **读取文件**：使用 Shell 命令读取文件内容
- **IPython 读取文件**：使用 Python 代码读取文件
- **追加内容**：向文件追加内容
- **读取更新后的文件**：验证追加的内容
- **目录列表**：列出工作目录内容

**预期结果：**
- 文件应成功创建和读取
- Shell 和 IPython 应共享相同的文件系统
- 文件内容应包含原始和追加的内容

### 5. 环境变量测试 (测试 19-22)

- **Shell 设置环境变量**：测试在 Shell 中设置环境变量
- **IPython 读取 Shell 环境变量**：验证环境变量隔离性
- **IPython 设置环境变量**：在 Python 中设置环境变量
- **IPython 读取 IPython 环境变量**：验证设置是否成功

**预期结果：**
- Shell 环境变量在 IPython 中不可见（预期行为）
- IPython 设置的环境变量在后续 IPython 执行中保持可见

### 6. 错误处理测试 (测试 23-27)

- **不存在的命令**：测试执行不存在的 Shell 命令
- **非零退出代码**：测试返回错误的 Shell 命令
- **Python 名称错误**：测试 NameError 异常处理
- **Python 语法错误**：测试 SyntaxError 异常处理
- **Python 除零错误**：测试 ZeroDivisionError 异常处理

**预期结果：**
- Shell 错误应返回适当的非零退出代码
- Python 错误应生成相应的异常信息
- 错误应通过 WebSocket 正确传递

### 7. 大型输出测试 (测试 28-29)

- **Shell 大量输出**：测试大量输出行的处理
- **IPython 大量输出**：测试 Python 生成大量输出的处理

**预期结果：**
- 所有输出行应通过 WebSocket 正确传递
- 应能处理至少 20 行输出而不丢失数据

### 8. 系统信息测试 (测试 30)

- **系统信息**：收集有关沙盒环境的详细信息

**预期结果：**
- 应返回 Linux 内核版本、Python 版本、工作目录等信息
- 所有信息应通过 WebSocket 可见

## WebSocket 输出解读

测试期间，您应该在 WebSocket 监控终端中看到类似以下格式的消息：

```json
{"type":"start","action_id":"xxx-xxx-xxx","data":{}}
{"type":"stream","action_id":"xxx-xxx-xxx","data":{"stream":"stdout","line":"输出内容"}}
{"type":"result","action_id":"xxx-xxx-xxx","data":{"exit_code":0,"error":null}}
{"type":"end","action_id":"xxx-xxx-xxx","data":{"exit_code":0,"error":""}}
```

消息类型说明：
- `start`：动作开始时发送
- `stream`：包含命令或代码的输出流（stdout/stderr）
- `result`：包含命令或代码执行的结果状态
- `end`：动作结束时发送，包含最终状态

正常情况下，大多数测试的 `exit_code` 应为 0，表示成功执行。错误处理测试应该返回非零退出码或包含错误信息。

## 故障排除

如果测试失败，请检查：

1. MentisRuntime 服务是否正在运行
2. 沙盒容器是否成功创建和启动
3. 沙盒 ID 是否正确
4. Docker 服务是否正常运行
5. Docker 镜像是否为最新构建的版本

常见问题：

- **"Agent stream ended without explicit result"**：这通常表示 Agent (MentisExecutor) 和 Runtime 之间的通信问题
- **"Result data format unexpected"**：这可能是观察结果格式的小问题，但通常不影响功能

## 进阶测试

完成基本测试后，您可以尝试：

1. 同时运行多个沙盒并进行测试
2. 测试长时间运行的命令
3. 测试大文件的创建和读取
4. 测试沙盒资源限制（CPU、内存）
5. 测试并发命令执行

这些高级测试可以帮助验证系统在更复杂场景下的表现。
