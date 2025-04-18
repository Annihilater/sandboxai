# MentisSandbox

MentisSandbox 是一个安全、持久化、具备实时反馈能力的沙箱环境，旨在为 AI Agent（特别是基于 LangGraph 构建的 Agent）提供可靠的执行后端。它使用 Docker 容器提供安全隔离，同时通过 WebSocket 实现实时通信，让 AI Agent 能够获取命令执行的即时反馈。

## 功能特点

### 安全性
- 通过 Docker 容器提供强隔离环境
- 限制资源使用
- 以非 root 用户运行内部进程

### 持久性
- 每个沙箱会话拥有持久化的文件系统 (`/work`)
- 支持长期运行的 Agent 会话

### 实时交互
- **Shell 命令执行**：安全执行 Shell 命令并获取实时反馈
- **IPython 代码执行**：在持久化的 IPython 环境中运行代码
- **WebSocket 实时通信**：获取命令执行过程中的流式输出和状态更新

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

1. **克隆代码库**

```bash
git clone https://github.com/yourusername/sandboxai.git
cd sandboxai
```

2. **构建 Docker 镜像**

```bash
make build-box-image
```

3. **启动 MentisRuntime 服务**

```bash
go run ./mentisruntime/main.go
```

## 快速开始

### 创建沙盒

```bash
curl -X POST http://127.0.0.1:5266/sandboxes
```

这将返回一个沙盒 ID，格式如：`{"sandbox_id":"752db9c2-0951-4b2c-a415-c2c8b6452cb2"}`

### 连接到 WebSocket 流

在一个单独的终端中，使用 `websocat` 连接到沙盒的 WebSocket 流：

```bash
websocat ws://127.0.0.1:5266/sandboxes/YOUR_SANDBOX_ID/stream
```

### 执行 Shell 命令

```bash
curl -X POST http://127.0.0.1:5266/sandboxes/YOUR_SANDBOX_ID/shell \
  -H "Content-Type: application/json" \
  -d '{"command": "echo \"Hello from MentisSandbox\""}'
```

### 执行 Python 代码

```bash
curl -X POST http://127.0.0.1:5266/sandboxes/YOUR_SANDBOX_ID/ipython \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"Hello from IPython\")", "split_output": true}'
```

## 测试

MentisSandbox 提供了一个全面的测试脚本 `test_sandbox.sh`，它包含 30 个测试用例，涵盖从基础功能到高级特性的各个方面。

### 运行测试

1. **启动 WebSocket 监控**

```bash
websocat ws://127.0.0.1:5266/sandboxes/YOUR_SANDBOX_ID/stream
```

2. **执行测试脚本**

```bash
chmod +x test_sandbox.sh
./test_sandbox.sh
```

更详细的测试指南，请查看 [测试文档](docs/TESTING.md)。

## 系统架构

MentisSandbox 由两个主要组件构成：

1. **MentisRuntime** (Go)：
   - 管理 Docker 容器的生命周期
   - 提供 REST API 接口
   - 管理 WebSocket 连接和消息广播
   - 处理命令执行和结果分发

2. **MentisExecutor** (Python)：
   - 运行在 Docker 容器内
   - 执行 Shell 命令和 IPython 代码
   - 将输出结果和执行状态实时推送到 Runtime

### 数据流架构

```
┌───────────────┐                 ┌───────────────────────────────────────────┐
│               │  1. HTTP API    │                                           │
│  外部客户端    │ ───────────────>│                                           │
│  (AI Agent)   │                 │           MentisRuntime (Go)              │
│               │  2. WebSocket   │                                           │
│               │<────────────────│                                           │
└───────────────┘                 └───────────────────┬───────────────────────┘
                                                     │
                                                     │ 3. Docker API
                                                     │
                                                     ▼
                                  ┌───────────────────────────────────────────┐
                                  │          Docker 容器                      │
                                  │                                           │
                                  │      MentisExecutor (Python)              │
                                  │                                           │
                                  └───────────────────────────────────────────┘
```

### 实时通信流程

```
┌───────────┐          ┌─────────────────┐          ┌────────────────┐
│           │  1. POST │                 │  3. POST │                │
│  客户端    │─────────>│   MentisRuntime │─────────>│ MentisExecutor │
│  (Agent)  │          │      (Go)       │          │    (Python)    │
│           │          │                 │          │                │
└─────┬─────┘          └────────┬────────┘          └───────┬────────┘
      │                         │                           │
      │ 2. WebSocket            │                           │
      │    连接                 │                           │
      │<────────────────────────┘                           │
      │                                                     │
      │                                                     │
      │                   4. 实时执行结果 (内部 HTTP)        │
      │<────────────────────────────────────────────────────┘
      │
      │ 5. WebSocket 消息流
      │ (stdout/stderr/状态更新)
      │<────────────────────────┐
      │                         │
      ▼                         │
┌───────────┐          ┌────────┴────────┐
│           │          │                 │
│  客户端    │          │   MentisRuntime │
│  (Agent)  │          │      (Go)       │
│           │          │                 │
└───────────┘          └─────────────────┘
```

## API 参考

### REST API

#### 沙箱管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/sandboxes` | POST | 创建新的沙盒实例 |
| `/sandboxes/{id}` | DELETE | 删除指定的沙盒实例 |

#### 命令执行

| 端点 | 方法 | 描述 |
|------|------|------|
| `/sandboxes/{id}/shell` | POST | 在沙盒中执行 Shell 命令 |
| `/sandboxes/{id}/ipython` | POST | 在沙盒中执行 IPython 代码 |

#### WebSocket

| 端点 | 描述 |
|------|------|
| `/sandboxes/{id}/stream` | 建立 WebSocket 连接，接收沙盒的实时输出流 |

### 消息格式

#### Shell 命令请求

```json
{
  "command": "echo \"Hello World\""
}
```

#### IPython 代码请求

```json
{
  "code": "print('Hello, IPython')",
  "split_output": true
}
```

#### WebSocket 消息类型

| 类型 | 描述 | 示例 |
|------|------|------|
| `start` | 动作开始 | `{"type":"start","action_id":"xxx","data":{}}` |
| `stream` | 标准输出/错误 | `{"type":"stream","action_id":"xxx","data":{"stream":"stdout","line":"输出内容"}}` |
| `result` | 执行结果 | `{"type":"result","action_id":"xxx","data":{"exit_code":0,"error":null}}` |
| `end` | 动作结束 | `{"type":"end","action_id":"xxx","data":{"exit_code":0,"error":""}}` |

## 未来计划

- 添加用户授权和认证
- 支持文件上传/下载
- 提供更多运行时环境选项
- 增强资源监控和限制功能
- 提供 Python 和 JavaScript 客户端库

## 贡献指南

请参阅 [贡献指南](docs/contributing.md) 文档。

## 许可证

[MIT 许可证](LICENSE)
