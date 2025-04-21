# MentisSandbox

MentisSandbox 是一个安全、持久化、具备实时反馈能力的沙箱环境，旨在为 AI Agent（特别是基于 LangGraph 构建的 Agent）提供可靠的执行后端。它使用 Docker 容器提供安全隔离，同时通过 WebSocket 实现实时通信，让 AI Agent 能够获取命令执行的即时反馈。

## 功能特点

### 安全性
- 通过 Docker 容器提供强隔离环境
- 限制资源使用 (未来计划)
- 以非 root 用户运行内部进程

### 持久性
- 每个沙箱会话拥有持久化的文件系统 (`/work`)
- 支持长期运行的 Agent 会话

### 实时交互
- **Shell 命令执行**：安全执行 Shell 命令并获取实时反馈
- **IPython 代码执行**：在持久化的 IPython 环境中运行代码
- **WebSocket 实时通信**：获取命令执行过程中的流式输出和状态更新

### 多租户与组织 (Spaces)
- **Spaces**: 提供逻辑隔离层，允许将沙箱分组管理。每个沙箱都属于一个 Space。

### 可扩展性
- 基础 Docker 镜像可自定义和配置
- 支持自托管部署
- 模块化设计便于未来功能扩展

## 安装与配置

### 前置要求

- Go 1.22+
- Docker
- Make (可选，用于构建脚本)
- WebSocket 客户端 (例如 `websocat`，用于测试)
- curl (用于 API 请求)

### 构建与启动

1.  **克隆代码库**

    ```bash
    git clone https://github.com/yourusername/sandboxai.git # 请替换为实际仓库地址
    cd sandboxai
    ```

2.  **构建 Docker 镜像** (包含 MentisExecutor)

    ```bash
    make build-box-image
    ```

3.  **启动 MentisRuntime 服务**

    ```bash
    go run ./mentisruntime/main.go
    ```
    服务默认监听在 `127.0.0.1:5266`。

## 快速开始

MentisRuntime 启动时会自动创建一个名为 `default` 的 Space。

### 1. 创建沙箱 (在 default Space 中)

```bash
curl -X POST http://127.0.0.1:5266/v1/spaces/default/sandboxes \
  -H "Content-Type: application/json" \
  -d '{}' # 可以留空，使用默认镜像
```

这将返回新创建沙箱的完整状态，包括其 ID：

```json
{
  "sandbox_id": "YOUR_SANDBOX_ID", 
  "ContainerID": "...",
  "AgentURL": "http://...", 
  "IsRunning": true, 
  "SpaceID": "default" 
}
```
**记下返回的 `sandbox_id` (YOUR_SANDBOX_ID)。**

### 2. 连接到 WebSocket 流

在一个单独的终端中，使用 `websocat` (或其他 WebSocket 客户端) 连接到沙箱的 WebSocket 流，以接收实时输出：

```bash
websocat ws://127.0.0.1:5266/v1/sandboxes/YOUR_SANDBOX_ID/stream
```
将 `YOUR_SANDBOX_ID` 替换为上一步获取到的 ID。

### 3. 执行 Shell 命令

```bash
curl -X POST http://127.0.0.1:5266/v1/spaces/default/sandboxes/YOUR_SANDBOX_ID/tools:run_shell_command \
  -H "Content-Type: application/json" \
  -d '{"command": "echo \"Hello from MentisSandbox Shell\" && sleep 2 && echo \"Shell Done.\""}'
```
你将在 `websocat` 连接的终端看到 "Hello from MentisSandbox Shell" 和 "Shell Done." 的输出。

### 4. 执行 Python 代码 (IPython)

```bash
curl -X POST http://127.0.0.1:5266/v1/spaces/default/sandboxes/YOUR_SANDBOX_ID/tools:run_ipython_cell \
  -H "Content-Type: application/json" \
  -d '{"code": "import time\nprint(\"Hello from IPython\")\ntime.sleep(2)\nprint(\"IPython Done.\")"}'
```
你将在 `websocat` 连接的终端看到 "Hello from IPython" 和 "IPython Done." 的输出。

### 5. 清理沙箱 (可选)

```bash
curl -X DELETE http://127.0.0.1:5266/v1/spaces/default/sandboxes/YOUR_SANDBOX_ID
```

## 测试

MentisSandbox 提供了一个全面的测试脚本 `test/test_sandbox.sh`，它包含多个测试用例，涵盖从基础功能到高级特性的各个方面。

### 运行测试

1.  **确保 MentisRuntime 服务正在运行。**
2.  **执行测试脚本**

    ```bash
    # 确保脚本有执行权限
    chmod +x test/test_sandbox.sh 
    # 运行测试
    ./test/test_sandbox.sh
    ```

更详细的测试指南，请查看 [TESTING.md](TESTING.md)。

## 系统架构

MentisSandbox 由两个主要组件构成：

1.  **MentisRuntime** (Go)：
    *   管理 Docker 容器 (Sandboxes) 的生命周期。
    *   管理 Spaces，提供逻辑分组。
    *   提供 REST API 接口用于管理 Spaces 和 Sandboxes，以及执行命令。
    *   管理 WebSocket 连接和消息广播，实现实时反馈。
    *   处理命令执行请求并将其分发给对应的 MentisExecutor。

2.  **MentisExecutor** (Python)：
    *   运行在每个 Docker 容器 (Sandbox) 内。
    *   监听来自 MentisRuntime 的命令执行请求 (通过内部 HTTP API)。
    *   执行 Shell 命令和 IPython 代码。
    *   将执行过程中的输出 (stdout/stderr) 和最终结果实时推送回 MentisRuntime (通过内部 HTTP API)。

### 数据流架构

```mermaid
graph LR
    subgraph Client
        A[外部客户端 / AI Agent]
    end

    subgraph MentisRuntime (Go)
        B(REST API Handler)
        C(WebSocket Hub)
        D(Sandbox Manager)
        E(Space Manager)
        F(Docker Client)
        G(Internal API Handler)
        B -- Manages --> E
        B -- Manages --> D
        D -- Uses --> F
        C -- Gets Updates --> D
        D -- Sends Commands --> H
        G -- Receives Observations --> D
    end
    
    subgraph Docker Container (Sandbox)
        H(MentisExecutor / Agent)
    end

    A -- 1. REST API (Manage/Execute) --> B
    A -- 2. WebSocket (Subscribe) --> C
    D -- 3. Docker API (Create/Start/Stop) --> F -- Controls --> H
    B -- 4. Internal HTTP (Execute Cmd) --> H
    H -- 5. Internal HTTP (Push Observations) --> G
    C -- 6. WebSocket (Push Stream/Result) --> A
```

### 实时通信流程 (以 Shell 命令为例)

```mermaid
sequenceDiagram
    participant Client as 客户端 (Agent)
    participant Runtime as MentisRuntime (Go)
    participant Executor as MentisExecutor (Python in Docker)

    Client->>+Runtime: 1. POST /v1/spaces/{sid}/sandboxes/{sbid}/tools:run_shell_command ({"command": "..."})
    Runtime->>Runtime: 2. 生成 ActionID, 验证 Sandbox 状态
    Runtime->>Executor: 3. POST /tools:run_shell_command (内部 API, 含 ActionID, command)
    Executor->>Executor: 4. 开始执行 Shell 命令
    Executor-->>Runtime: 5. POST /v1/internal/observations/{sbid} (type: stream, data: stdout/stderr line)
    Runtime-->>Client: 6. WebSocket 推送 (type: stream)
    Executor-->>Runtime: 7. POST /v1/internal/observations/{sbid} (type: stream, data: ...)
    Runtime-->>Client: 8. WebSocket 推送 (type: stream)
    Executor->>Executor: 9. Shell 命令执行完毕
    Executor-->>Runtime: 10. POST /v1/internal/observations/{sbid} (type: result, data: exit_code, error)
    Runtime-->>Client: 11. WebSocket 推送 (type: result)
    Runtime-->>Client: 12. WebSocket 推送 (type: end)
    Runtime->>-Client: 13. HTTP 202 Accepted (含 action_id) [此响应在步骤2之后立即返回]

```

## API 参考

所有 API 端点均以 `/v1` 为前缀。

### 健康检查

| 端点        | 方法 | 描述           | 成功响应 (200 OK) |
| ----------- | ---- | -------------- | ----------------- |
| `/health`   | GET  | 检查服务健康状态 | `{"status":"ok"}` |

### Space 管理

| 端点             | 方法   | 描述                 | 请求体 (示例)                                                                 | 成功响应 (201/200/204)                                                                                                |
| ---------------- | ------ | -------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `/spaces`        | POST   | 创建新的 Space       | `{"name": "my-project", "description": "...", "metadata": {"key": "value"}}` | `201 Created` - `{"space_id": "...", "name": "...", ...}`                                                            |
| `/spaces`        | GET    | 列出所有 Spaces      | N/A                                                                           | `200 OK` - `[{"ID": "default", ...}, {"ID": "my-project", ...}]`                                                      |
| `/spaces/{sid}`  | GET    | 获取指定 Space 信息  | N/A                                                                           | `200 OK` - `{"ID": "...", "Name": "...", "Sandboxes": {"sbid1": {...}, ...}}` (包含其下的 Sandbox 状态) |
| `/spaces/{sid}`  | PUT    | 更新 Space 信息      | `{"description": "new desc", "metadata": {"new": "data"}}`                    | `200 OK` - 更新后的 Space 状态                                                                                        |
| `/spaces/{sid}`  | DELETE | 删除指定 Space       | N/A                                                                           | `204 No Content`                                                                                                      |

### Sandbox 管理

| 端点                         | 方法   | 描述                     | 请求体 (示例)                               | 成功响应 (201/200/204)         |
| ---------------------------- | ------ | ------------------------ | ------------------------------------------- | ------------------------------ |
| `/spaces/{sid}/sandboxes`    | POST   | 在指定 Space 创建新 Sandbox | `{"image": "custom-image:tag"}` (可选) | `201 Created` - Sandbox 状态 |
| `/spaces/{sid}/sandboxes/{sbid}` | GET    | 获取指定 Sandbox 状态    | N/A                                         | `200 OK` - Sandbox 状态      |
| `/spaces/{sid}/sandboxes/{sbid}` | DELETE | 删除指定 Sandbox         | N/A                                         | `204 No Content`               |

*   `{sid}`: Space ID (例如 `default`)
*   `{sbid}`: Sandbox ID

### 命令执行 (异步)

这些端点会立即返回 `202 Accepted` 和一个 `action_id`，实际执行结果通过 WebSocket 推送。

| 端点                                       | 方法 | 描述                     | 请求体 (示例)                               | 成功响应 (202 Accepted)        |
| ------------------------------------------ | ---- | ------------------------ | ------------------------------------------- | ------------------------------ |
| `/spaces/{sid}/sandboxes/{sbid}/tools:run_shell_command` | POST | 执行 Shell 命令          | `{"command": "ls -l /work"}`                | `{"action_id": "..."}`         |
| `/spaces/{sid}/sandboxes/{sbid}/tools:run_ipython_cell`  | POST | 执行 IPython 代码        | `{"code": "print(1+1)"}`                    | `{"action_id": "..."}`         |

### WebSocket

| 端点                         | 描述                                       |
| ---------------------------- | ------------------------------------------ |
| `/sandboxes/{sbid}/stream`   | 建立 WebSocket 连接，接收指定 Sandbox 的实时输出流 |

*注意：WebSocket 端点路径当前不包含 `spaceID`。*

### WebSocket 消息格式 (Observation)

所有通过 WebSocket 发送的消息都遵循以下基本结构，具体内容在 `data` 字段中：

```json
{
  "observation_type": "start" | "stream" | "result" | "error" | "end",
  "action_id": "...", // 关联的动作 ID
  // ... 其他字段根据 observation_type 不同而变化
  "timestamp": "..." // ISO 8601 格式时间戳
}
```

| `observation_type` | `data` 字段内容 (示例)                                                                 | 描述                                     |
| ------------------ | -------------------------------------------------------------------------------------- | ---------------------------------------- |
| `start`            | `{}` (可能包含 action 类型等元数据)                                                      | 动作开始                                 |
| `stream`           | `{"stream": "stdout" | "stderr", "line": "输出内容"}`                                   | 标准输出或标准错误流中的一行文本         |
| `result`           | `{"exit_code": 0, "error": null}` (Shell) 或 `{"output": "...", "error": null}` (IPython) | 命令或代码执行的最终结果                 |
| `error`            | `{"message": "错误信息", "details": "..."}`                                            | 执行过程中发生的错误 (例如 Agent 内部错误) |
| `end`              | `{"exit_code": 0, "error": null}` (可能包含最终状态)                                     | 动作结束 (无论成功或失败)                |

## 未来计划

- 添加用户授权和认证
- 支持文件上传/下载到 `/work` 目录
- 提供更多运行时环境选项 (例如 Node.js)
- 增强资源监控和限制功能
- 提供官方 Python 和 JavaScript/TypeScript 客户端库

## 贡献指南

请参阅 [贡献指南](docs/contributing.md) 文档。

## 许可证

[MIT 许可证](LICENSE)
