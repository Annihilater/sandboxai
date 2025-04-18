**核心目标 (Phase 1):**

在保留原始 SandboxAI 核心架构（Go 后端管理 Docker + Python Agent 在容器内执行）和核心功能（执行 Shell 命令、执行 IPython Cell）的基础上，**引入基于 WebSocket/SSE 的实时通信机制**，以支持外部 Agent（如 LangGraph 构建的）能够实时获取执行过程中的输出流和异步观察结果 (Observation)。**本阶段不增加新的 Action 类型（如文件操作、浏览器），也不集成 Playwright 或额外的 Go/Rust 运行时。**

**项目名称:** MentisSandbox
**组件名称:**

  * Go 后端: `MentisRuntime` (原 `sandboxaid`)
  * Python Agent: `MentisExecutor` (原 `boxd`)
  * Python Client SDK: `mentis_client` (原 `sandboxai-client`)


-----

**MentisSandbox Phase 1 - 详细改造指南**


-----

## 1\. 项目结构调整与重命名

  * **强制性步骤:** 为了清晰区分改造后的代码，必须执行以下重命名。
  * **操作:**
    1.  将 `go/sandboxaid/` 重命名为 `go/mentisruntime/`。
    2.  全局搜索替换 Go 代码中的包名 `sandboxaid` 为 `mentisruntime`。
    3.  将 `go/sandboxaid/main.go` 重命名为 `go/mentisruntime/main.go`。
    4.  将 `python/boxd/` 重命名为 `python/mentis_executor/`。
    5.  全局搜索替换 Python 代码中的包名/引用 `boxd` 为 `mentis_executor`。
    6.  将 `python/boxd/Dockerfile` 移动到 `images/mentis-executor/Dockerfile`。
    7.  将 `api/v1.yaml` 复制或重命名为 `api/mentis/v1.yaml`。
    8.  (可选) 将 Python 客户端库目录 `python/sandboxai/` 重命名为 `python/mentis_client/` 并更新内部引用。

-----

## 2\. API 规范更新 (`api/mentis/v1.yaml`)

  * **目标:** 定义新的实时通信端点，明确现有动作端点的行为变更，并定义用于实时通信的 Observation 结构。

<!-- end list -->

```yaml
openapi: 3.0.0
info:
  title: MentisSandbox API
  version: 1.0.0
  description: API for managing persistent sandboxes with real-time interaction capabilities.
servers:
  - url: /v1 # Base path

paths:
  /sandboxes:
    post:
      summary: Create a new sandbox instance.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SandboxSettings' # Reuse or adapt original settings
      responses:
        '201':
          description: Sandbox created successfully.
          content:
            application/json:
              schema:
                type: object
                properties:
                  sandbox_id: # Changed from space/name to single ID
                    type: string
                    format: uuid
                  # Potentially return initial status or WebSocket URL
        # ... other error responses ...

  /sandboxes/{sandbox_id}:
    delete:
      summary: Delete a sandbox instance.
      parameters:
        - name: sandbox_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '204':
          description: Sandbox deleted successfully.
        # ... other error responses (e.g., 404 Not Found) ...

  /sandboxes/{sandbox_id}/shell:
    post:
      summary: Execute a shell command (results streamed via WebSocket/SSE).
      parameters:
        - name: sandbox_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                command:
                  type: string
                timeout: # Timeout for the command itself
                  type: integer
                  format: int32
                  default: 300
                work_dir:
                  type: string
                  default: "/workspace"
                env:
                  type: object
                  additionalProperties: { type: string }
              required:
                - command
      responses:
        '202':
          description: Command accepted for execution. Results will be streamed.
          content:
            application/json:
              schema:
                type: object
                properties:
                  action_id:
                    type: string
                    format: uuid # ID to correlate observations
        # ... other error responses (e.g., 404 Sandbox Not Found, 400 Bad Request) ...

  /sandboxes/{sandbox_id}/ipython:
    post:
      summary: Execute an IPython cell (results streamed via WebSocket/SSE).
      parameters:
        - name: sandbox_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                code:
                  type: string
                timeout: # Timeout for cell execution
                  type: integer
                  format: int32
                  default: 300
              required:
                - code
      responses:
        '202':
          description: Cell accepted for execution. Results will be streamed.
          content:
            application/json:
              schema:
                type: object
                properties:
                  action_id:
                    type: string
                    format: uuid
        # ... other error responses ...

  /sandboxes/{sandbox_id}/stream:
    get:
      summary: Establish a WebSocket/SSE connection for real-time observations.
      description: Upgrades the connection to WebSocket or starts an SSE stream to receive observations for the specified sandbox.
      parameters:
        - name: sandbox_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '101': # Switching Protocols (WebSocket)
          description: WebSocket connection established. Messages follow the StreamMessage schema.
        '200': # OK (SSE)
          description: SSE stream established. Events follow the StreamMessage schema.
          content:
            text/event-stream:
              schema:
                type: string # Describes SSE format
        # ... other error responses (e.g., 404 Sandbox Not Found) ...

components:
  schemas:
    SandboxSettings: # Adapt from original SandboxAI v1.yaml
      type: object
      properties:
        image_id:
          type: string
          description: "Custom Docker image ID to use (optional, overrides default)."
        env_vars:
          type: object
          additionalProperties:
            type: string
          description: Environment variables for the sandbox.
        cpu_limit:
          type: number
          format: float
          description: "CPU limit in cores (e.g., 0.5, 1.0)."
        memory_limit_mb:
          type: integer
          format: int32
          description: "Memory limit in Megabytes."
        # Add volume/persistence options if needed for explicit control
        # timeout: # Overall sandbox inactivity timeout?

    # --- Observation Schemas (Phase 1) ---
    BaseObservation:
      type: object
      required:
        - observation_type
        - timestamp
      properties:
        observation_type:
          type: string
        action_id:
          type: string
          format: uuid
          nullable: true
          description: ID of the action that triggered this observation, if applicable.
        timestamp:
          type: string
          format: date-time

    CmdStartObservation:
      # ... (as defined in previous thought block) ...
      allOf:
        - $ref: '#/components/schemas/BaseObservation'
        - type: object
          properties:
            command: { type: string }
            pid: { type: integer }
          required: [command, pid]

    CmdOutputObservationPart:
      # ... (as defined previously) ...
       allOf:
        - $ref: '#/components/schemas/BaseObservation'
        - type: object
          properties:
            pid: { type: integer }
            stream: { type: string, enum: [stdout, stderr] }
            data: { type: string }
          required: [pid, stream, data]

    CmdEndObservation:
      # ... (as defined previously) ...
      allOf:
        - $ref: '#/components/schemas/BaseObservation'
        - type: object
          properties:
            pid: { type: integer }
            command: { type: string }
            exit_code: { type: integer }
          required: [pid, command, exit_code]

    IPythonStartObservation:
       allOf:
        - $ref: '#/components/schemas/BaseObservation'
        - type: object
          properties:
            code: { type: string }
            execution_count: { type: integer, nullable: true }
          required: [code]

    IPythonOutputObservationPart:
       allOf:
        - $ref: '#/components/schemas/BaseObservation'
        - type: object
          properties:
            stream: { type: string, enum: [stdout, stderr, display_data, execute_result] } # Add more types as needed from Jupyter spec
            data: { type: object } # Could be string for stdout/err, or richer object for display_data/result
            # Potentially add mime-type for display_data
          required: [stream, data]

    IPythonResultObservation:
        allOf:
         - $ref: '#/components/schemas/BaseObservation'
         - type: object
           properties:
             status: { type: string, enum: [ok, error] }
             execution_count: { type: integer }
             error_name: { type: string, nullable: true }
             error_value: { type: string, nullable: true }
             traceback: { type: array, items: { type: string }, nullable: true }
           required: [status, execution_count]

    ErrorObservation:
        allOf:
         - $ref: '#/components/schemas/BaseObservation'
         - type: object
           properties:
             message: { type: string }
             details: { type: string, nullable: true }
           required: [message]

    AgentStateObservation: # Basic placeholder for async events
        allOf:
         - $ref: '#/components/schemas/BaseObservation'
         - type: object
           properties:
             message: { type: string }
             state_details: { type: object }
           required: [message]

    StreamMessage:
        description: A message sent over the WebSocket/SSE stream for Phase 1.
        oneOf:
          - $ref: '#/components/schemas/CmdStartObservation'
          - $ref: '#/components/schemas/CmdOutputObservationPart'
          - $ref: '#/components/schemas/CmdEndObservation'
          - $ref: '#/components/schemas/IPythonStartObservation'
          - $ref: '#/components/schemas/IPythonOutputObservationPart'
          - $ref: '#/components/schemas/IPythonResultObservation'
          - $ref: '#/components/schemas/ErrorObservation'
          - $ref: '#/components/schemas/AgentStateObservation'

```

-----

## 3\. Runtime Service (`MentisRuntime`) 改造 (Go)

**目标:** 添加 WebSocket/SSE 支持，修改 Action 处理以支持异步执行和结果流式传输，处理内部 Observation 推送。

### 3.1. 主程序与服务器设置 (`go/mentisruntime/main.go`)

  * **修改内容:**
      * 引入 WebSocket Hub (`ws.Hub`)。
      * 初始化 Hub 并运行它。
      * 将 Hub 实例注入 `SandboxManager` 和 `APIHandler`。
      * 在路由器中添加 `/stream` 的 WebSocket/SSE 升级处理器。
      * 在路由器中添加 `/internal/observations/{sandbox_id}` 的 POST 处理器。
      * 确保 `SandboxManager` 被正确初始化并注入依赖。

<!-- end list -->

```go
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"time"
	"mentisruntime/config"
	"mentisruntime/handler"
	"mentisruntime/manager"
	"mentisruntime/ws" // NEW: WebSocket package

	"github.com/docker/docker/client"
	"github.com/gorilla/mux" // Or your preferred router
)

func main() {
	// --- Setup Logger, Load Config, Init Docker Client (as before) ---
	// ... (Use code from previous thought block, ensure cfg includes InternalObservationListenAddr) ...
	ctx := context.Background()
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.Load() // Ensure cfg has ports, docker host, InternalObservationListenAddr, etc.
	if err != nil { /* ... handle error ... */ }
	dockerClient, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil { /* ... handle error ... */ }
	defer dockerClient.Close()

	// --- Initialize WebSocket Hub ---
	hub := ws.NewHub(logger)
	go hub.Run() // Start Hub's event loop in a separate goroutine

	// --- Initialize Sandbox Manager ---
	// Pass the hub to the manager so it can send observations
	sandboxManager, err := manager.NewSandboxManager(ctx, dockerClient, hub, cfg, logger)
	if err != nil {
		logger.Error("Failed to create Sandbox Manager", "error", err)
		os.Exit(1)
	}

	// --- Initialize Handlers ---
	apiHandler := handler.NewAPIHandler(sandboxManager, hub, cfg, logger) // Pass Hub

	// --- Setup Router ---
	r := mux.NewRouter()

	// REST API Routes (Existing actions need behavior change)
	r.HandleFunc("/sandboxes", apiHandler.CreateSandboxHandler).Methods("POST")
	r.HandleFunc("/sandboxes/{sandbox_id}", apiHandler.DeleteSandboxHandler).Methods("DELETE")
	r.HandleFunc("/sandboxes/{sandbox_id}/shell", apiHandler.PostShellCommandHandler).Methods("POST") // Modified Handler
	r.HandleFunc("/sandboxes/{sandbox_id}/ipython", apiHandler.PostIPythonCellHandler).Methods("POST") // Modified Handler
	// r.HandleFunc("/sandboxes/{sandbox_id}/status", apiHandler.GetStatusHandler).Methods("GET") // Optional

	// --- WebSocket/SSE Route ---
	// The handler function `serveWs` will handle the upgrade and client registration
	r.HandleFunc("/sandboxes/{sandbox_id}/stream", func(w http.ResponseWriter, r *http.Request) {
		ws.ServeWs(hub, sandboxManager, w, r, logger) // Pass manager for validation if needed
	})

	// --- Internal Observation Route ---
	// This should ideally listen on a separate port or be protected
	// to only accept connections from internal Docker network.
	internalRouter := mux.NewRouter() // Example: separate router/port
	internalRouter.HandleFunc("/internal/observations/{sandbox_id}", apiHandler.InternalObservationHandler).Methods("POST")

	// Example: Run internal server on a different port
	go func() {
		internalAddr := ":" + cfg.InternalObservationPort // e.g., ":8081"
		logger.Info("Starting Internal Observation server", "port", cfg.InternalObservationPort)
		if err := http.ListenAndServe(internalAddr, internalRouter); err != nil && err != http.ErrServerClosed {
			logger.Error("Internal server failed", "error", err)
			// Handle error appropriately, maybe signal main goroutine
		}
	}()


	// --- Start Main Server ---
	srv := &http.Server{
		Addr:    ":" + cfg.ServerPort, // e.g., ":8080"
		Handler: r,
		// ... timeouts ...
	}
	logger.Info("Starting MentisRuntime server", "port", cfg.ServerPort)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Error("Server failed", "error", err)
		os.Exit(1)
	}
}
```

### 3.2. WebSocket/SSE Hub 实现 (`go/mentisruntime/ws/hub.go`, `go/mentisruntime/ws/client.go`)

  * **目标:** 管理客户端 WebSocket/SSE 连接，并将来自 `SandboxManager` 的消息路由到正确的客户端。
  * **实现:** 基本可以复用之前 "NexusSandbox" 设计中的 Hub 逻辑。
      * **`hub.go`:**
          * `Hub` 结构体包含 `clients`, `register`, `unregister`, `sandboxBroadcast map[string]map[*Client]bool`, `sendToSandbox chan *SandboxMessage`, `logger`。
          * `NewHub()` 构造函数。
          * `Run()` 方法：核心事件循环，处理注册/注销，并从 `sendToSandbox` channel 读取消息，查找 `sandboxBroadcast` 中的订阅者并发送。**关键:** 发送消息时，需要将 `[]byte` 推送到每个匹配客户端的 `send` channel。
      * **`client.go`:**
          * `Client` 结构体包含 `hub`, `conn *websocket.Conn`, `send chan []byte`, `sandboxID string`。
          * `readPump()`: 从 WS 读取消息（主要是处理关闭和 ping/pong）。
          * `writePump()`: 从 `client.send` channel 读取消息并写入 WS。
      * **`handler.go` (`serveWs`)**:
          * 处理 HTTP 升级请求。
          * 创建 `Client` 对象。
          * 注册 Client 到 Hub (`hub.register <- client`)。
          * 将 Client 添加到 Hub 的 `sandboxBroadcast[sandboxID]` 集合中。
          * 启动 `readPump` 和 `writePump` goroutine。

<!-- end list -->

```go
// Example snippet for Hub.Run() loop - sending part
case message := <-h.sendToSandbox:
    // Find clients subscribed to this sandboxID
    h.sandboxClientsMu.RLock() // Use RWMutex for sandboxBroadcast
    clientsMap, ok := h.sandboxBroadcast[message.SandboxID]
    h.sandboxClientsMu.RUnlock()

    if ok {
        h.logger.Debug("Broadcasting message", "sandboxID", message.SandboxID, "num_clients", len(clientsMap))
        for client := range clientsMap {
            select {
            case client.send <- message.Message: // Send message to client's buffer
            default:
                // Buffer full, client might be slow or disconnected
                h.logger.Warn("Client send buffer full, closing connection", "sandboxID", client.sandboxID)
                // Optionally close and unregister client here or let writePump handle it
                close(client.send)
                delete(clientsMap, client) // Need write lock for this part if modifying map directly
            }
        }
    } else {
        h.logger.Debug("No clients subscribed", "sandboxID", message.SandboxID)
    }
```

```go
// Example snippet for serveWs (in ws/handler.go or similar)
func ServeWs(hub *Hub, manager *manager.SandboxManager, w http.ResponseWriter, r *http.Request, logger *slog.Logger) {
    vars := mux.Vars(r)
    sandboxID := vars["sandbox_id"]

    // Optional: Validate sandboxID exists using manager
    // exists := manager.SandboxExists(sandboxID)
    // if !exists {
    //     http.NotFound(w, r)
    //     return
    // }

    // Use gorilla/websocket upgrader
    conn, err := upgrader.Upgrade(w, r, nil) // Configure upgrader appropriately
    if err != nil {
        logger.Error("WebSocket upgrade failed", "error", err, "sandboxID", sandboxID)
        return
    }

    client := NewClient(hub, conn, sandboxID, logger)
    client.hub.register <- client // Register client with the hub

    // Register client for sandbox-specific broadcasts
    hub.SubscribeClientToSandbox(client, sandboxID) // Hub needs this method

    logger.Info("WebSocket client connected", "sandboxID", sandboxID, "remoteAddr", conn.RemoteAddr())

    // Allow collection of memory referenced by the caller by doing all work in new goroutines.
    go client.writePump()
    go client.readPump() // This will handle unregistration on disconnect
}

// Hub needs SubscribeClientToSandbox and UnsubscribeClientFromSandbox methods
func (h *Hub) SubscribeClientToSandbox(client *Client, sandboxID string) {
	h.sandboxClientsMu.Lock()
	defer h.sandboxClientsMu.Unlock()
	if _, ok := h.sandboxBroadcast[sandboxID]; !ok {
		h.sandboxBroadcast[sandboxID] = make(map[*Client]bool)
	}
	h.sandboxBroadcast[sandboxID][client] = true
	h.logger.Debug("Client subscribed", "sandboxID", sandboxID, "clientCount", len(h.sandboxBroadcast[sandboxID]))
}

// Unsubscribe called from client.readPump on disconnect or hub.unregister
func (h *Hub) UnsubscribeClientFromSandbox(client *Client, sandboxID string) {
    h.sandboxClientsMu.Lock()
    defer h.sandboxClientsMu.Unlock()
    if clients, ok := h.sandboxBroadcast[sandboxID]; ok {
        if _, ok := clients[client]; ok {
            delete(clients, client)
            h.logger.Debug("Client unsubscribed", "sandboxID", sandboxID, "remainingClients", len(clients))
            if len(clients) == 0 {
                delete(h.sandboxBroadcast, sandboxID)
                h.logger.Debug("Last client unsubscribed, removing sandbox broadcast entry", "sandboxID", sandboxID)
            }
        }
    }
}

// Hub.Run needs to handle client.hub.unregister channel messages
// case client := <-h.unregister:
//    h.UnsubscribeClientFromSandbox(client, client.sandboxID) // Ensure proper cleanup
//    close(client.send) // Already handled? Double check client close logic.
```

### 3.3. Sandbox 管理器 (`go/mentisruntime/manager/manager.go`)

  * **修改 `CreateSandbox`:**
      * 确保传递给容器的环境变量包含 `SANDBOX_ID` 和正确的 `RUNTIME_OBSERVATION_URL`。
      * 需要可靠地获取容器的内部 IP 地址。
  * **修改 `ExecuteShellCommand` / `ExecuteIPythonCell` (或创建新的 `InitiateAction`):**
      * **核心改变:** 此函数不再等待执行完成。
      * 生成 `action_id` (UUID)。
      * 获取 `SandboxState`，确认容器运行中，获取内部 Agent URL (`http://<ip>:<port>/shell` or `/ipython`).
      * 构造包含 `action_id` 和原始命令/代码的 JSON 请求体。
      * **启动一个新的 Goroutine** (`go handleActionExecution(...)`) 来执行实际的 HTTP 请求并处理（流式）响应。
      * `InitiateAction` 函数立即返回 `action_id` 和 `nil` 错误。
  * **新函数 `handleActionExecution(...)`:**
      * 接收 `ctx`, `sandboxID`, `agentURL`, `actionID`, `requestBody []byte`。
      * 使用 `http.Client` 发送 POST 请求到 `agentURL`。
      * **处理响应 (关键):**
          * 检查 HTTP 状态码。如果非 2xx，读取错误信息，格式化 `ErrorObservation` (包含 `action_id`)，通过 `hub.sendToSandbox` 发送，然后返回/退出 goroutine。
          * 如果响应表明是流式（根据 Action 类型或 Content-Type），使用 `bufio.NewReader` 或类似方式**逐行或逐块读取**响应体。
          * 对于每个数据块/行，将其包装在相应的 `Observation` 结构中（如 `CmdOutputObservationPart`, `IPythonOutputObservationPart`），包含 `action_id`，序列化为 JSON。
          * 将序列化后的 Observation 发送到 `hub.sendToSandbox`。
          * **特别注意:** 读取流可能阻塞，使用带超时的 Context (`ctx`) 控制。处理读取错误。
          * 流结束后（或对于非流式响应），解析可能的最终状态（如 `CmdEndObservation` 可能在流末尾或单独发送），发送最终 Observation。
      * 需要管理这个 goroutine 的生命周期（例如，通过 `context.CancelFunc`）。
  * **`ReceiveInternalObservation`:** 实现基本不变，接收 POST 请求，解析 JSON，发送到 `hub.sendToSandbox`。

<!-- end list -->

```go
// manager/manager.go

type SandboxManager struct {
    // ... (dockerClient, activeSandboxes, wsHub, config, logger, mutex) ...
    httpClient *http.Client // Add http client for internal comms
}

func NewSandboxManager(/*... deps ...*/) (*SandboxManager, error) {
    // ... init ...
    httpClient := &http.Client{
        Timeout: 30 * time.Second, // Adjust timeout
        // Configure transport if needed (e.g., specific network interface)
    }
    return &SandboxManager{/*...,*/ httpClient: httpClient}, nil
}


// Modified execution function pattern
func (m *SandboxManager) InitiateAction(ctx context.Context, sandboxID string, actionType string, actionPayload map[string]interface{}) (string, error) {
	m.mutex.RLock() // RLock since we only read state here
	state, ok := m.activeSandboxes[sandboxID]
	m.mutex.RUnlock()

	if !ok {
		return "", fmt.Errorf("sandbox not found: %s", sandboxID)
	}
	if state.Status != "RUNNING" {
		return "", fmt.Errorf("sandbox not running: %s, status: %s", sandboxID, state.Status)
	}

	actionID := uuid.New().String() // Generate unique action ID
	actionPayload["action_id"] = actionID // Inject action ID into payload

	// Determine target path based on actionType
	var targetPath string
	switch actionType {
	case "shell":
		targetPath = "/shell" // Matches MentisExecutor endpoint
	case "ipython":
		targetPath = "/ipython"
	// Add cases for future actions if API structure changes
	default:
		return "", fmt.Errorf("unsupported action type for initiation: %s", actionType)
	}
	agentURL := fmt.Sprintf("http://%s:%s%s", state.ContainerIP, state.AgentPort, targetPath)

	requestBody, err := json.Marshal(actionPayload)
	if err != nil {
		return "", fmt.Errorf("failed to marshal action payload: %w", err)
	}

	// Launch background goroutine to handle execution and streaming
	go m.handleActionExecution(context.Background(), sandboxID, actionID, agentURL, requestBody, actionType) // Use background context

	m.logger.Info("Action initiated", "sandboxID", sandboxID, "actionID", actionID, "actionType", actionType)
	return actionID, nil // Return immediately
}


// Goroutine function to handle the actual execution and streaming/pushing results
func (m *SandboxManager) handleActionExecution(ctx context.Context, sandboxID, actionID, agentURL string, requestBody []byte, actionType string) {
    req, err := http.NewRequestWithContext(ctx, "POST", agentURL, bytes.NewReader(requestBody))
    if err != nil {
        m.pushErrorObservation(sandboxID, actionID, fmt.Sprintf("Failed to create request: %v", err))
        return
    }
    req.Header.Set("Content-Type", "application/json")

    resp, err := m.httpClient.Do(req)
    if err != nil {
        m.pushErrorObservation(sandboxID, actionID, fmt.Sprintf("Failed to execute action request: %v", err))
        return
    }
    defer resp.Body.Close()

    // --- Crucial: Handle potentially streaming response ---
    // For Phase 1, assume /shell and /ipython will stream JSON lines (Observations)
    if resp.StatusCode >= 200 && resp.StatusCode < 300 {
        m.logger.Debug("Received successful response header, starting to read body", "actionID", actionID, "statusCode", resp.StatusCode)
        // Use a scanner to read line-by-line JSON observations yielded by MentisExecutor's StreamingResponse
        scanner := bufio.NewScanner(resp.Body)
        for scanner.Scan() {
            lineBytes := scanner.Bytes()
            if len(lineBytes) == 0 {
                continue // Skip empty lines
            }
            m.logger.Debug("Received stream data", "actionID", actionID, "data", string(lineBytes))

            // Forward the raw JSON observation line directly to the hub
            // Ensure the observation JSON from MentisExecutor includes action_id
            m.pushRawObservation(sandboxID, lineBytes)
        }
        if err := scanner.Err(); err != nil {
            m.pushErrorObservation(sandboxID, actionID, fmt.Sprintf("Error reading streaming response body: %v", err))
        } else {
             m.logger.Info("Finished streaming response body", "actionID", actionID)
             // Final observation (like CmdEndObservation) should be sent by the stream itself.
        }

    } else {
        // Handle non-2xx responses from MentisExecutor
        bodyBytes, _ := io.ReadAll(resp.Body)
        errorMsg := fmt.Sprintf("MentisExecutor failed action (HTTP %d): %s", resp.StatusCode, string(bodyBytes))
        m.pushErrorObservation(sandboxID, actionID, errorMsg)
    }
}


// Helper to push raw JSON observation bytes to the hub
func (m *SandboxManager) pushRawObservation(sandboxID string, messageBytes []byte) {
    msg := &ws.SandboxMessage{
        SandboxID: sandboxID,
        Message:   messageBytes,
    }
    // Non-blocking send to hub's channel
    select {
    case m.wsHub.SendToSandbox <- msg:
    default:
        m.logger.Warn("WebSocket Hub channel full, dropping observation", "sandboxID", sandboxID)
    }
}

// Helper to push ErrorObservation
func (m *SandboxManager) pushErrorObservation(sandboxID, actionID, errorMessage string) {
    obs := map[string]interface{}{
        "observation_type": "ErrorObservation",
        "action_id":        actionID,
        "timestamp":        time.Now().UTC().Format(time.RFC3339Nano),
        "message":          errorMessage,
    }
    jsonBytes, err := json.Marshal(obs)
    if err != nil {
        m.logger.Error("Failed to marshal error observation", "error", err)
        return
    }
    m.pushRawObservation(sandboxID, jsonBytes)
}


// ReceiveInternalObservation implementation
func (m *SandboxManager) ReceiveInternalObservation(sandboxID string, observationBytes []byte) error {
	m.mutex.RLock() // Check if sandbox exists and is tracked
	_, ok := m.activeSandboxes[sandboxID]
	m.mutex.RUnlock()

	if !ok {
		// Maybe log this, but don't error loudly, could be race condition on delete
		m.logger.Warn("Received observation for untracked/deleted sandbox", "sandboxID", sandboxID)
		return fmt.Errorf("sandbox not tracked: %s", sandboxID)
	}

    m.logger.Debug("Received internal observation push", "sandboxID", sandboxID, "data", string(observationBytes))
	m.pushRawObservation(sandboxID, observationBytes)
	return nil
}

```

### 3.4. API 处理器 (`go/mentisruntime/handler/handler.go`)

  * **修改 `PostShellCommandHandler` / `PostIPythonCellHandler`:**
      * 解析请求体。
      * 调用 `manager.InitiateAction(ctx, sandboxID, "shell" or "ipython", payload)`。
      * 如果 `InitiateAction` 返回错误，写入 HTTP 错误响应。
      * 如果成功，获取 `action_id` 并返回 HTTP 202 Accepted，响应体为 `{"action_id": action_id}`。
  * **实现 `InternalObservationHandler`:**
      * 解析 URL 获取 `sandbox_id`。
      * 读取请求体 (`[]byte`)。
      * 调用 `manager.ReceiveInternalObservation(sandboxID, bodyBytes)`。
      * 返回 HTTP 200 OK 或错误。

<!-- end list -->

```go
// handler/handler.go

func (h *APIHandler) PostShellCommandHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	sandboxID := vars["sandbox_id"]

	var payload map[string]interface{} // Use map for flexibility initially
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "Invalid request body: "+err.Error(), http.StatusBadRequest)
		return
	}
	// Basic validation
	if _, ok := payload["command"]; !ok {
		http.Error(w, "Missing 'command' in request body", http.StatusBadRequest)
		return
	}

	// Add 'action_type' for clarity if needed, or manager adds it
	// payload["action_type"] = "shell"

	actionID, err := h.manager.InitiateAction(r.Context(), sandboxID, "shell", payload)
	if err != nil {
		h.logger.Error("Failed to initiate shell command", "error", err, "sandboxID", sandboxID)
		// Determine appropriate HTTP status code based on error type
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, err.Error(), http.StatusNotFound)
		} else if strings.Contains(err.Error(), "not running") {
			http.Error(w, err.Error(), http.StatusConflict) // 409 Conflict
		} else {
			http.Error(w, "Failed to initiate action: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted) // 202 Accepted
	json.NewEncoder(w).Encode(map[string]string{"action_id": actionID})
}

// Implement PostIPythonCellHandler similarly, calling InitiateAction with type "ipython"

func (h *APIHandler) InternalObservationHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	sandboxID := vars["sandbox_id"]

	bodyBytes, err := io.ReadAll(r.Body)
	if err != nil {
		h.logger.Error("Failed to read internal observation body", "error", err, "sandboxID", sandboxID)
		http.Error(w, "Failed to read request body", http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	if len(bodyBytes) == 0 {
		http.Error(w, "Empty observation body", http.StatusBadRequest)
		return
	}


	err = h.manager.ReceiveInternalObservation(sandboxID, bodyBytes)
	if err != nil {
		// Log error, but maybe still return 200 OK to MentisExecutor unless it's critical
		// e.g., if sandbox is gone, executor doesn't need to retry indefinitely.
		h.logger.Warn("Failed to process internal observation", "error", err, "sandboxID", sandboxID)
		// Decide appropriate response code, 200 might be okay to ack receipt even if processing failed downstream
	}

	w.WriteHeader(http.StatusOK)
}

```

### 3.5. 内部通信与流处理

  * **关键:** `MentisRuntime` 在调用 `MentisExecutor` 的 `/shell` 或 `/ipython` 时，需要处理流式响应。`handleActionExecution` goroutine 使用 `bufio.Scanner` 逐行读取（假设 `MentisExecutor` 每行输出一个 JSON Observation）。
  * **异步 Observation:** `MentisExecutor` 通过向 `MentisRuntime` 的 `/internal/observations/{sandbox_id}` 端点发送 POST 请求来推送事件。`MentisRuntime` 需要能从 Docker 网络内部接收这些请求。

-----

## 4\. Sandbox Agent (`MentisExecutor`) 改造 (Python)

**目标:** 修改 `/shell` 和 `/ipython` 端点以支持流式响应输出，并实现异步 Observation 推送。

### 4.1. 主程序与依赖 (`python/mentis_executor/main.py`, `requirements.txt`)

  * **`requirements.txt`:**
    ```
    fastapi
    uvicorn[standard]
    pydantic
    httpx # For pushing observations
    ipykernel # For /ipython
    jupyter_client # For /ipython
    # aiofiles - If needed for future file actions
    ```
  * **`main.py`:**
      * 设置 FastAPI app，添加 `lifespan` 用于管理 `httpx.AsyncClient`。
      * 从环境变量读取 `SANDBOX_ID` 和 `RUNTIME_OBSERVATION_URL`。
      * 实现 `push_observation` 函数。
      * 保留 `/shell`, `/ipython` 端点，添加 `/health`。

<!-- end list -->

```python
# python/mentis_executor/main.py
import os
import asyncio
import logging
import json
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, AsyncGenerator
import httpx

# Assuming ipython_handler.py and shell_handler.py contain the core logic now
from .ipython_handler import handle_ipython_request
from .shell_handler import handle_shell_request

# --- Configuration ---
SANDBOX_ID = os.environ.get("NEXUS_SANDBOX_ID", "unknown_sandbox")
RUNTIME_OBSERVATION_URL_TEMPLATE = os.environ.get("NEXUS_RUNTIME_OBSERVATION_URL") # Template like http://host:port/internal/observations/{sandbox_id}
RUNTIME_OBSERVATION_URL = RUNTIME_OBSERVATION_URL_TEMPLATE.format(sandbox_id=SANDBOX_ID) if RUNTIME_OBSERVATION_URL_TEMPLATE else None

# --- Logging ---
# ... (setup logging as before) ...
logger = logging.getLogger(__name__)

# --- HTTP Client for Push ---
# Manage the client lifecycle using FastAPI's lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MentisExecutor lifespan startup.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        app.state.http_client = client
        yield
    logger.info("MentisExecutor lifespan shutdown.")

app = FastAPI(lifespan=lifespan)

# --- Observation Pushing ---
# (Use push_observation function from previous thought block)
async def push_observation(observation: Dict[str, Any]):
    """Sends an observation back to the Runtime Service."""
    if not RUNTIME_OBSERVATION_URL: # Check if URL is configured
        logger.warning("RUNTIME_OBSERVATION_URL not set. Cannot push observation.")
        return

    # Ensure essential fields are present
    observation.setdefault("sandbox_id", SANDBOX_ID) # Add sandbox ID if missing
    observation.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    push_url = RUNTIME_OBSERVATION_URL # URL already includes sandbox_id

    try:
        client: httpx.AsyncClient = app.state.http_client # Get client from app state
        response = await client.post(push_url, json=observation)
        response.raise_for_status() # Raise exception for 4xx/5xx errors
        logger.debug(f"Pushed observation {observation.get('observation_type')} with status {response.status_code}")
    except httpx.RequestError as exc:
        logger.error(f"HTTP Error pushing observation to {push_url}: {exc}")
    except Exception as e:
        logger.error(f"Unexpected error pushing observation: {e}")


# --- Pydantic Models for Requests (Phase 1) ---
class ShellRequest(BaseModel):
    action_id: str # Expect action_id from Runtime
    command: str
    work_dir: Optional[str] = "/workspace"
    env: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 300

class IPythonRequest(BaseModel):
    action_id: str
    code: str
    timeout: Optional[int] = 300

# --- API Endpoints ---
@app.post("/shell")
async def execute_shell(request: ShellRequest):
    logger.info(f"Received /shell request: action_id={request.action_id}")
    try:
        # handle_shell_request should now be an async generator
        # or return one that yields Observation JSON strings
        stream_generator = handle_shell_request(request, push_observation_callback=push_observation)
        # Return a streaming response where each yielded item is a JSON string observation
        # Need to ensure newline separation for scanner on Go side
        async def json_line_stream():
            async for observation_dict in stream_generator:
                try:
                    yield json.dumps(observation_dict) + "\n"
                except Exception as e:
                    logger.error(f"Error serializing observation for streaming: {e}")
                    # Yield an error observation instead?
                    error_obs = {
                        "observation_type": "ErrorObservation",
                        "action_id": request.action_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": f"Serialization error: {e}"
                    }
                    yield json.dumps(error_obs) + "\n"


        return StreamingResponse(json_line_stream(), media_type="application/x-ndjson")
    except Exception as e:
        logger.exception(f"Error initiating shell command for action_id={request.action_id}: {e}")
        # Push error observation asynchronously
        await push_observation({
             "observation_type": "ErrorObservation",
             "action_id": request.action_id,
             "message": f"Failed to initiate shell command: {str(e)}",
             "details": traceback.format_exc()
        })
        raise HTTPException(status_code=500, detail=f"Failed to initiate shell command: {str(e)}")

@app.post("/ipython")
async def execute_ipython(request: IPythonRequest):
    logger.info(f"Received /ipython request: action_id={request.action_id}")
    try:
        # handle_ipython_request should also return an async generator yielding Observation JSON strings
        stream_generator = handle_ipython_request(request, push_observation_callback=push_observation)
        async def json_line_stream():
             async for observation_dict in stream_generator:
                try:
                    yield json.dumps(observation_dict) + "\n"
                except Exception as e:
                     logger.error(f"Error serializing IPython observation for streaming: {e}")
                     error_obs = { # ... similar error observation ...}
                     yield json.dumps(error_obs) + "\n"

        return StreamingResponse(json_line_stream(), media_type="application/x-ndjson")
    except Exception as e:
        logger.exception(f"Error initiating ipython cell for action_id={request.action_id}: {e}")
        await push_observation({
             "observation_type": "ErrorObservation",
             "action_id": request.action_id,
             "message": f"Failed to initiate IPython cell: {str(e)}",
             "details": traceback.format_exc()
        })
        raise HTTPException(status_code=500, detail=f"Failed to initiate IPython cell: {str(e)}")


@app.get("/health")
async def health_check():
    # TODO: Add more checks if needed (e.g., ipython kernel status?)
    return {"status": "ok"}

```

### 4.2. Shell 命令处理 (`python/mentis_executor/shell_handler.py` - 流式响应)

  * **目标:** 使用 `asyncio.subprocess` 执行命令，并将 `stdout`/`stderr` 实时作为 `Observation` `yield` 出去。
  * **实现:**

<!-- end list -->

```python
# python/mentis_executor/shell_handler.py
import asyncio
import logging
import json
import os
import shlex # Use shlex for safer command parsing if needed, though we execute raw command string here
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any

from .main import ShellRequest, push_observation # Assuming push_observation is accessible or passed

logger = logging.getLogger(__name__)

async def read_stream(stream: asyncio.StreamReader, stream_name: str, pid: int, action_id: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Reads a stream line by line and yields CmdOutputObservationPart."""
    while not stream.at_eof():
        try:
            line = await stream.readline()
            if line:
                yield {
                    "observation_type": "CmdOutputObservationPart",
                    "action_id": action_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pid": pid,
                    "stream": stream_name,
                    "data": line.decode(errors='replace').rstrip() # Decode safely
                }
            else:
                # End of stream reached
                break
        except Exception as e:
            logger.error(f"Error reading {stream_name} for pid {pid}: {e}")
            yield {
                "observation_type": "ErrorObservation",
                "action_id": action_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Error reading {stream_name}: {e}",
                "details": f"PID: {pid}"
            }
            break # Stop reading on error

async def handle_shell_request(request: ShellRequest, push_observation_callback: callable) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Handles shell command execution, yielding observations as JSON strings.
    Yields CmdStartObservation, CmdOutputObservationPart(s), CmdEndObservation, or ErrorObservation.
    """
    pid = -1 # Default PID if process fails to start
    process = None
    action_id = request.action_id

    try:
        # Prepare environment
        # Inherit current env and merge request env (be careful with security)
        current_env = os.environ.copy()
        if request.env:
            current_env.update(request.env)

        # Use shell=True cautiously. Better: parse command and args if possible.
        # For simplicity here, we run the raw command string via bash.
        # NOTE: This is a potential security risk if command contains untrusted input.
        # Consider using shlex.split() and running without shell=True if feasible.
        command_to_run = ["/bin/bash", "-c", request.command]

        # Change working directory if specified and exists
        cwd = request.work_dir or "/workspace"
        if not os.path.isdir(cwd):
             # Yield error and exit if work_dir is invalid
             logger.error(f"Working directory not found: {cwd}")
             yield {
                 "observation_type": "ErrorObservation",
                 "action_id": action_id,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "message": f"Working directory not found: {cwd}",
             }
             return

        logger.info(f"Executing shell command in '{cwd}': {request.command}")

        process = await asyncio.create_subprocess_exec(
            *command_to_run,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=current_env,
            limit=1024 * 1024 # Set buffer limit (e.g., 1MB)
        )
        pid = process.pid
        logger.info(f"Process started with PID: {pid} for action_id: {action_id}")

        # Yield Start Observation
        yield {
            "observation_type": "CmdStartObservation",
            "action_id": action_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": request.command,
            "pid": pid
        }

        # Concurrently read stdout and stderr and yield observations
        async def stream_output():
            tasks = [
                asyncio.create_task(read_stream(process.stdout, 'stdout', pid, action_id)),
                asyncio.create_task(read_stream(process.stderr, 'stderr', pid, action_id))
            ]
            for task in asyncio.as_completed(tasks):
                try:
                    stream_gen = await task
                    async for observation in stream_gen:
                        yield observation # Yield each part as it arrives
                except Exception as e:
                     logger.error(f"Error processing stream task for pid {pid}: {e}")
                     # Yield error observation
                     yield {
                         "observation_type": "ErrorObservation",
                         "action_id": action_id,
                         "timestamp": datetime.now(timezone.utc).isoformat(),
                         "message": f"Stream processing error: {e}",
                         "details": f"PID: {pid}"
                     }

        # Yield all output parts
        async for observation_part in stream_output():
            yield observation_part

        # Wait for process completion and get exit code
        logger.debug(f"Waiting for process {pid} to complete...")
        try:
            # Use timeout if provided in request
            exit_code = await asyncio.wait_for(process.wait(), timeout=request.timeout)
            logger.info(f"Process {pid} finished with exit code: {exit_code}")
        except asyncio.TimeoutError:
            logger.warning(f"Process {pid} timed out after {request.timeout} seconds. Killing...")
            try:
                process.kill()
                await process.wait() # Wait after killing
            except ProcessLookupError:
                logger.info(f"Process {pid} already exited.")
            except Exception as kill_err:
                logger.error(f"Error killing process {pid}: {kill_err}")

            # Yield timeout error observation
            yield {
                "observation_type": "ErrorObservation",
                "action_id": action_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Command timed out after {request.timeout} seconds.",
                "details": f"PID: {pid}, Command: {request.command}"
            }
            # Also yield a CmdEndObservation with a special exit code? Or rely on ErrorObservation?
            # Let's yield CmdEnd with non-zero code for consistency.
            exit_code = -1 # Indicate timeout


        # Yield End Observation
        yield {
            "observation_type": "CmdEndObservation",
            "action_id": action_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pid": pid,
            "command": request.command,
            "exit_code": exit_code
        }

    except FileNotFoundError as e:
         logger.error(f"Command not found for action_id={action_id}: {e}")
         yield {
             "observation_type": "ErrorObservation",
             "action_id": action_id,
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "message": f"Command not found: {e.filename}",
         }
    except Exception as e:
        logger.exception(f"Error in handle_shell_request for action_id={action_id}: {e}")
        yield { # Ensure final error is yielded if something goes wrong
            "observation_type": "ErrorObservation",
            "action_id": action_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": f"Internal error processing shell command: {str(e)}",
            "details": traceback.format_exc() if pid == -1 else f"PID: {pid}" # Include PID if process started
        }
        # Ensure process is killed if started but failed mid-stream
        if process and process.returncode is None:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass # Ignore errors during cleanup kill

```

### 4.3. IPython Cell 处理 (`python/mentis_executor/ipython_handler.py` - 流式响应)

  * **目标:** 改造原有的 IPython 执行逻辑（通常使用 `jupyter_client`），使其能异步监听 ZMQ 消息并 `yield` 对应的 `Observation`。
  * **挑战:** `jupyter_client` 的 ZMQ 通信本身是异步的，但将其集成到 FastAPI 的 `StreamingResponse` 中需要仔细处理 `asyncio` 和 ZMQ 事件循环。
  * **实现思路:**
    1.  **获取 Kernel Client:** 需要一个共享的（或按需创建/管理的）`jupyter_client.AsyncKernelClient` 实例。
    2.  **发送执行请求:** 调用 `kernel_client.execute(request.code)`。这会返回一个 `msg_id`。
    3.  **异步监听 IOPub:** **关键！** 在 `StreamingResponse` 的 `async def stream_generator()` 中，需要异步地循环调用 `kernel_client.get_iopub_msg(timeout=...)`。
    4.  **处理消息:**
          * 收到 `status` 消息（`busy`, `idle`）可以忽略或用于内部状态。
          * 收到 `execute_input` 消息可以忽略。
          * 收到 `stream` 消息 (stdout/stderr)，`yield` `IPythonOutputObservationPart`。
          * 收到 `display_data` / `execute_result` / `update_display_data` 消息，提取内容（可能需要处理 `data` 字典中的不同 MIME 类型），`yield` `IPythonOutputObservationPart` 或专门的 Observation。
          * 收到 `error` 消息，提取错误信息，`yield` `IPythonResultObservation` (status='error') 或 `ErrorObservation`，**并停止监听该 `msg_id`**。
          * **等待 `execute_reply`:** 需要同时（或在 `iopub` 监听循环外）异步等待 `kernel_client.get_shell_msg(timeout=...)` 以获取与 `msg_id` 匹配的 `execute_reply` 消息。这个消息标志着 Cell 执行完成。
          * 当收到对应的 `execute_reply` 且 `status=='ok'` 或 `status=='error'` 时，`yield` 最终的 `IPythonResultObservation`，**并停止监听该 `msg_id`**。
    5.  **超时处理:** `get_iopub_msg` 和 `get_shell_msg` 都需要设置超时。如果整体执行超时，需要发送中断请求 (`kernel_client.interrupt_kernel()`)，`yield` `ErrorObservation`，并停止。
    6.  **内核管理:** 需要考虑内核的启动、关闭、重启逻辑（可能由 `MentisRuntime` 控制或 `MentisExecutor` 内部管理）。

<!-- end list -->

```python
# python/mentis_executor/ipython_handler.py
# NOTE: This is complex and requires careful asyncio/jupyter_client handling.
# Consider using a dedicated class to manage kernel state and message handling.
# This is a simplified conceptual outline.

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any
from jupyter_client.async_client import AsyncKernelClient # Requires kernel setup
import uuid

from .main import IPythonRequest, push_observation # Assuming push_observation is accessible

logger = logging.getLogger(__name__)

# --- Kernel Management (Needs proper implementation) ---
# This should likely be managed globally or per-session within MentisExecutor
# For simplicity, assume a function `get_kernel_client()` exists.
# Real implementation needs connection files, starting kernels etc.
async def get_kernel_client() -> AsyncKernelClient:
    # Placeholder: In reality, connect to or start a kernel
    # This needs significant setup (connection file, starting kernel process)
    # raise NotImplementedError("Kernel client management not fully implemented in this example")
    # --- Mock Example ---
    class MockKernelClient:
        async def execute(self, code): return str(uuid.uuid4()) # Return mock msg_id
        async def get_iopub_msg(self, timeout=1):
             # Simulate receiving messages (replace with actual ZMQ polling)
             await asyncio.sleep(0.1) # Simulate work
             # Example messages (yield one by one in a real scenario)
             if MockKernelClient.state == 0:
                 MockKernelClient.state = 1
                 return {'msg_type': 'stream', 'content': {'name': 'stdout', 'text': 'Output line 1\n'}}
             elif MockKernelClient.state == 1:
                 MockKernelClient.state = 2
                 return {'msg_type': 'execute_result', 'content': {'data': {'text/plain': "'result'"}, 'execution_count': 1}}
             else:
                 await asyncio.sleep(timeout) # Simulate timeout if no more messages
                 raise TimeoutError()
        async def get_shell_msg(self, timeout=1):
            await asyncio.sleep(0.3) # Simulate reply delay
            # Simulate receiving execute_reply
            if MockKernelClient.state == 2:
                 MockKernelClient.state = 0 # Reset for next call
                 return {'msg_type': 'execute_reply', 'content': {'status': 'ok', 'execution_count': 1}}
            else:
                await asyncio.sleep(timeout)
                raise TimeoutError()
        async def is_alive(self): return True
        # ... other methods ...
    MockKernelClient.state = 0
    return MockKernelClient()
# --- End Mock Example ---


async def handle_ipython_request(request: IPythonRequest, push_observation_callback: callable) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Handles IPython cell execution, yielding observations as JSON strings.
    """
    kernel_client = None
    exec_count = None # Store execution count if available
    action_id = request.action_id

    try:
        kernel_client = await get_kernel_client()
        if not await kernel_client.is_alive():
            raise RuntimeError("IPython kernel is not alive.")

        logger.info(f"Executing IPython code for action_id: {action_id}")

        # Send execute request
        msg_id = await kernel_client.execute(request.code)
        logger.debug(f"Execute request sent, msg_id: {msg_id}")

        # Yield Start Observation (might not have exec_count yet)
        yield {
            "observation_type": "IPythonStartObservation",
            "action_id": action_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "code": request.code,
            "execution_count": None # Usually available later
        }

        # Asynchronously listen for IOPub messages and Shell reply
        # This part is tricky and requires careful handling of async tasks and timeouts

        iopub_task = None
        shell_task = None
        done = False
        timeout = request.timeout or 300

        async def iopub_listener():
            nonlocal exec_count, done
            while not done:
                try:
                    # Short timeout to allow checking shell reply or main timeout
                    msg = await kernel_client.get_iopub_msg(timeout=1)
                    msg_type = msg['msg_type']
                    content = msg.get('content', {})
                    parent_header_msg_id = msg.get('parent_header', {}).get('msg_id')

                    # Ignore messages not related to our request
                    if parent_header_msg_id != msg_id:
                        continue

                    logger.debug(f"Received IOPub message: type={msg_type}, msg_id={msg_id}")

                    if msg_type == 'execute_input':
                        exec_count = content.get('execution_count') # Capture execution count
                        continue # Ignore input echo

                    obs = {
                       "observation_type": "IPythonOutputObservationPart",
                       "action_id": action_id,
                       "timestamp": datetime.now(timezone.utc).isoformat(),
                       "stream": msg_type,
                       "data": None,
                       # Add execution_count if available?
                    }

                    if msg_type == 'stream':
                        obs["data"] = content.get('text')
                    elif msg_type in ['display_data', 'execute_result', 'update_display_data']:
                         obs["data"] = content.get('data') # Rich data dict by mime type
                         if msg_type == 'execute_result':
                             exec_count = content.get('execution_count')
                    elif msg_type == 'error':
                         # Error on IOPub usually signals end of execution
                         # Yield final result here and signal done
                         done = True
                         final_obs = {
                            "observation_type": "IPythonResultObservation",
                            "action_id": action_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "status": "error",
                            "execution_count": exec_count or -1,
                            "error_name": content.get('ename'),
                            "error_value": content.get('evalue'),
                            "traceback": content.get('traceback'),
                         }
                         yield final_obs
                         return # Stop listening

                    # Yield the observation part if data was found
                    if obs.get("data") is not None:
                         yield obs

                except TimeoutError:
                    # No message received in a while, continue loop unless main timeout hit
                    continue
                except Exception as e:
                    logger.exception(f"Error reading IOPub for msg_id {msg_id}: {e}")
                    done = True # Stop on error
                    yield { # Yield error and stop
                        "observation_type": "ErrorObservation",
                        "action_id": action_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": f"Error reading IPython IOPub stream: {str(e)}",
                    }
                    return # Stop listening


        async def shell_listener():
            nonlocal exec_count, done
            while not done:
                try:
                     # Short timeout to allow checking main timeout
                    msg = await kernel_client.get_shell_msg(timeout=1)
                    msg_type = msg['msg_type']
                    content = msg.get('content', {})
                    parent_header_msg_id = msg.get('parent_header', {}).get('msg_id')

                    if parent_header_msg_id != msg_id:
                        continue

                    logger.debug(f"Received Shell message: type={msg_type}, msg_id={msg_id}")

                    if msg_type == 'execute_reply':
                        done = True # Signal completion
                        status = content.get('status')
                        exec_count = content.get('execution_count')
                        final_obs = {
                            "observation_type": "IPythonResultObservation",
                            "action_id": action_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "status": status,
                            "execution_count": exec_count or -1,
                        }
                        if status == 'error':
                             final_obs["error_name"] = content.get('ename')
                             final_obs["error_value"] = content.get('evalue')
                             final_obs["traceback"] = content.get('traceback')

                        yield final_obs
                        return # Stop listening
                except TimeoutError:
                     continue
                except Exception as e:
                    logger.exception(f"Error reading Shell reply for msg_id {msg_id}: {e}")
                    done = True # Stop on error
                    yield { # Yield error and stop
                        "observation_type": "ErrorObservation",
                        "action_id": action_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": f"Error reading IPython Shell reply stream: {str(e)}",
                    }
                    return # Stop listening


        # Run listeners concurrently with overall timeout
        try:
            # Create tasks
            iopub_task = asyncio.create_task(iopub_listener())
            shell_task = asyncio.create_task(shell_listener())
            listeners = [iopub_task, shell_task]

            # Wait for tasks with timeout
            # We need to yield results as they come from listeners
            async def combined_generator():
                pending = set(listeners)
                while pending and not done: # Also check 'done' flag set by listeners
                    # Wait for any task to complete or timeout (use short waits?)
                    # Or better: yield from each listener as results become available
                    # This requires a more complex async generator merging pattern
                    # Simplified: Yield from iopub first as it gives intermediate results
                    try:
                        async for obs in iopub_task: # This needs modification, iopub_task returns generator
                            yield obs
                    except asyncio.CancelledError: pass # Task was cancelled

                    try:
                         async for obs in shell_task: # This also needs modification
                            yield obs
                    except asyncio.CancelledError: pass

                    # This simplified yielding isn't quite right for concurrent generators.
                    # A better approach uses asyncio.as_completed or asyncio.gather
                    # combined with yielding results immediately.

                    # --- Placeholder for a more robust async merge ---
                    # A simple but less real-time way: wait for both to finish
                    # await asyncio.wait(listeners, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                    # Check results, yield, check 'done' flag... complex logic.
                    # Let's assume for now the listeners yield directly (conceptual)
                    # --- End Placeholder ---

                    # TEMPORARY SIMPLIFICATION: Poll tasks (not ideal)
                    await asyncio.sleep(0.1) # Prevent busy loop


            # Use asyncio.wait or gather with timeout on the listeners
            # This part needs careful implementation to handle timeouts and yield results correctly.
            # Simplified yielding from tasks directly (conceptual - actual implementation is more complex)
            done_tasks, pending_tasks = await asyncio.wait(listeners, timeout=timeout, return_when=asyncio.ALL_COMPLETED)

            if pending_tasks: # Timeout occurred before both finished normally
                 logger.warning(f"IPython execution timed out for action_id: {action_id}")
                 for task in pending_tasks:
                     task.cancel()
                 # Yield timeout error
                 yield {
                    "observation_type": "ErrorObservation",
                    "action_id": action_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": f"IPython cell execution timed out after {timeout} seconds.",
                 }

        except Exception as e:
             logger.exception(f"Error managing IPython listeners for action_id={action_id}: {e}")
             yield { # Final safety net error
                 "observation_type": "ErrorObservation",
                 "action_id": action_id,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "message": f"Internal error during IPython execution: {str(e)}",
             }
        finally:
             # Ensure tasks are cancelled if generator exits early
             if iopub_task and not iopub_task.done(): iopub_task.cancel()
             if shell_task and not shell_task.done(): shell_task.cancel()


    except Exception as e:
        logger.exception(f"Error in handle_ipython_request for action_id={action_id}: {e}")
        yield { # Ensure final error is yielded
            "observation_type": "ErrorObservation",
            "action_id": action_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": f"Failed to process IPython request: {str(e)}",
            "details": traceback.format_exc()
        }

```

**注意:** 上述 `handle_ipython_request` 的实现是高度**概念性**的，因为它涉及到复杂的 `asyncio` 和 `jupyter_client` ZMQ 消息处理。实际实现需要更健壮的错误处理、任务管理和超时逻辑。可能需要引入额外的辅助类来管理内核客户端的生命周期和消息流。

### 4.4. 异步 Observation 推送

  * `push_observation` 函数在 `main.py` 中实现，使用 `httpx.AsyncClient` 向 `RUNTIME_OBSERVATION_URL` 发送 POST 请求。
  * Action Handlers 在需要发送非流式结果或异步事件时调用此函数。

-----

## 5\. Docker 镜像更新 (`images/mentis-executor/Dockerfile`)

  * **目标:** 构建包含 Python3, `MentisExecutor` 及其依赖 (FastAPI, Uvicorn, httpx, ipykernel, jupyter\_client), 并以非 root 用户运行的基础镜像。**Phase 1 不需要 Go, Rust, Node, Playwright。**

<!-- end list -->

```dockerfile
# Use a base image with Python pre-installed, e.g., python:3.11-slim
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install common utilities needed? (curl, git might be useful later, but not strictly for Phase 1)
# RUN apt-get update && apt-get install -y --no-install-recommends curl git gosu && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN groupadd -r sandboxgroup && useradd -r -g sandboxgroup -m -d /home/sandboxuser -s /bin/bash sandboxuser

# Create and set permissions for workspace
RUN mkdir /workspace && chown sandboxuser:sandboxgroup /workspace

# Copy application code and requirements
# Adjust source path based on your project layout
COPY ./python/mentis_executor /app/mentis_executor
COPY ./python/requirements.txt /app/requirements.txt
WORKDIR /app

# Install Python dependencies
# Consider using a virtual environment inside the container
RUN pip install --no-cache-dir -r requirements.txt

# Change ownership of the app directory
RUN chown -R sandboxuser:sandboxgroup /app

# Set default working directory for commands executed inside the container
WORKDIR /workspace
# Switch to non-root user
USER sandboxuser

# Expose the internal port MentisExecutor will listen on
EXPOSE 8080

# Start the MentisExecutor service using uvicorn
CMD ["uvicorn", "mentis_executor.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

-----

## 6\. Client SDK (`mentis_client`) 改造 (Python)

  * **目标:** 提供连接到 `/stream` 端点并处理 Observation 的能力。修改 `run_` 方法的行为。
  * **文件:** `python/mentis_client/sandbox.py` (或新建 `client.py`)

<!-- end list -->

```python
# python/mentis_client/sandbox.py (Conceptual Changes)
import httpx
import websockets # Or use httpx for SSE
import asyncio
import threading
import json
import uuid
from typing import Callable, Dict, Any, Optional

# Assume BASE_URL is configured for the MentisRuntime service
BASE_URL = "http://localhost:8080" # Example

class MentisSandbox:
    def __init__(self, sandbox_id: str, base_url: str = BASE_URL):
        self.sandbox_id = sandbox_id
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/v1"
        self.stream_url_ws = f"ws://{self.base_url.split('//')[-1]}/v1/sandboxes/{self.sandbox_id}/stream"
        self.stream_url_sse = f"{self.base_url}/v1/sandboxes/{self.sandbox_id}/stream" # Assuming SSE uses HTTP(S)
        self._client = httpx.Client(timeout=30.0) # Sync client for API calls
        self._stream_task = None
        self._stop_event = threading.Event()
        self._ws_conn = None

    @classmethod
    def create(cls, settings: Optional[Dict[str, Any]] = None, base_url: str = BASE_URL) -> 'MentisSandbox':
        """Creates a new sandbox."""
        url = f"{base_url.rstrip('/')}/v1/sandboxes"
        with httpx.Client(timeout=60.0) as client: # Longer timeout for creation
            response = client.post(url, json=settings or {})
            response.raise_for_status()
            data = response.json()
            return cls(sandbox_id=data['sandbox_id'], base_url=base_url)

    def delete(self):
        """Deletes the sandbox."""
        url = f"{self.api_url}/sandboxes/{self.sandbox_id}"
        try:
            response = self._client.delete(url)
            response.raise_for_status()
        finally:
            self.disconnect_stream() # Ensure stream is disconnected on delete
            self._client.close()

    def _post_action(self, action_type: str, payload: Dict[str, Any]) -> str:
        """Sends an action request and returns action_id."""
        # Ensure action_id is included for tracking (optional, could be done server-side)
        action_id = str(uuid.uuid4())
        # payload["action_id"] = action_id # Send it if executor expects it
        # Determine endpoint based on action_type for Phase 1
        endpoint_map = {"shell": "shell", "ipython": "ipython"}
        path = endpoint_map.get(action_type)
        if not path:
            raise ValueError(f"Unsupported action type in Phase 1: {action_type}")

        url = f"{self.api_url}/sandboxes/{self.sandbox_id}/{path}"
        response = self._client.post(url, json=payload)
        response.raise_for_status() # Raise for 4xx/5xx
        if response.status_code == 202:
            return response.json().get("action_id", action_id) # Return server-provided or client-generated ID
        else:
            # Should not happen if server follows spec, but handle defensively
            raise RuntimeError(f"Unexpected status code {response.status_code} from action endpoint")


    def run_shell_command(self, command: str, work_dir: Optional[str]=None, env: Optional[Dict[str,str]]=None, timeout: Optional[int]=None) -> str:
        """Initiates a shell command execution."""
        payload = {"command": command}
        if work_dir: payload["work_dir"] = work_dir
        if env: payload["env"] = env
        if timeout: payload["timeout"] = timeout
        return self._post_action("shell", payload)

    def run_ipython_cell(self, code: str, timeout: Optional[int]=None) -> str:
        """Initiates an IPython cell execution."""
        payload = {"code": code}
        if timeout: payload["timeout"] = timeout
        return self._post_action("ipython", payload)


    def connect_stream(self, callback: Callable[[Dict[str, Any]], None], use_sse: bool = False):
        """Connects to the observation stream (WebSocket or SSE) and runs listener in background thread."""
        if self._stream_task and self._stream_task.is_alive():
            print("Stream already connected.")
            return

        self._stop_event.clear()

        if use_sse:
             # Placeholder for SSE implementation using httpx streaming or sseclient-py
             raise NotImplementedError("SSE client not fully implemented in this example.")
             # self._stream_task = threading.Thread(target=self._sse_listener, args=(callback,))
        else:
            self._stream_task = threading.Thread(target=self._websocket_listener, args=(callback,), daemon=True)

        self._stream_task.start()
        print(f"Connecting to {'SSE' if use_sse else 'WebSocket'} stream for {self.sandbox_id}...")


    def _websocket_listener(self, callback: Callable[[Dict[str, Any]], None]):
        """Background thread function to listen to WebSocket."""
        async def listen():
            uri = self.stream_url_ws
            while not self._stop_event.is_set():
                try:
                    async with websockets.connect(uri) as websocket:
                        self._ws_conn = websocket # Store connection if needed for sending later
                        print(f"WebSocket connected to {uri}")
                        while not self._stop_event.is_set():
                            try:
                                message = await asyncio.wait_for(websocket.recv(), timeout=5.0) # Timeout to check stop_event
                                try:
                                    observation = json.loads(message)
                                    callback(observation) # Call user callback
                                except json.JSONDecodeError:
                                    print(f"Received non-JSON WebSocket message: {message}")
                                except Exception as e:
                                    print(f"Error in WebSocket callback: {e}")
                            except asyncio.TimeoutError:
                                continue # Check stop_event again
                            except websockets.exceptions.ConnectionClosedOK:
                                print("WebSocket connection closed normally.")
                                break # Exit inner loop to reconnect
                            except websockets.exceptions.ConnectionClosedError as e:
                                print(f"WebSocket connection closed with error: {e}")
                                break # Exit inner loop to reconnect
                except Exception as e:
                    print(f"WebSocket connection failed: {e}")
                finally:
                    self._ws_conn = None

                if not self._stop_event.is_set():
                    print("WebSocket disconnected. Reconnecting in 5 seconds...")
                    await asyncio.sleep(5) # Wait before reconnecting

        try:
            asyncio.run(listen())
        except Exception as e:
             print(f"WebSocket listener thread exited with error: {e}")


    def disconnect_stream(self):
        """Signals the listener thread to stop and disconnect."""
        print("Disconnecting stream...")
        self._stop_event.set()
        # If using websockets, closing might need async context or thread join
        # Simple approach: set stop event, let thread exit on next timeout/error
        if self._stream_task:
             self._stream_task.join(timeout=2.0) # Wait briefly for thread to exit
             if self._stream_task.is_alive():
                 print("Warning: Stream listener thread did not exit cleanly.")
        self._stream_task = None
        print("Stream disconnected.")

    # Ensure proper cleanup in __del__ or context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.delete() # Example: Auto-delete on exit context

```

-----

## 7\. 配置与环境变量

  * **`MentisRuntime` (Go - `config/config.go`):**
      * `ServerPort`: "8080" (外部 API)
      * `InternalObservationPort`: "8081" (内部监听)
      * `InternalObservationHost`: "0.0.0.0" (监听所有内部接口)
      * `DockerHost`: "" (使用 DOCKER\_HOST env var 或默认 socket)
      * `DefaultExecutorImage`: "your\_registry/mentis-executor:latest" (要构建的镜像)
      * `DefaultCpuLimit`: 1.0
      * `DefaultMemoryLimitMB`: 512
      * `WorkspaceBasePath`: "/mnt/mentis\_workspaces" (宿主机上存储 Volume 的基础路径)
  * **`MentisExecutor` (Python - Dockerfile ENV):**
      * `NEXUS_SANDBOX_ID`: 由 `MentisRuntime` 在创建容器时注入。
      * `NEXUS_RUNTIME_OBSERVATION_URL`: 由 `MentisRuntime` 在创建容器时注入 (e.g., `http://<runtime_ip>:8081/internal/observations/{sandbox_id}`).

-----

## 8\. 错误处理与健壮性

  * **`MentisRuntime`:**
      * 使用 `log/slog` 进行结构化日志记录。
      * 处理 Docker API 调用错误。
      * 处理内部 HTTP 请求错误。
      * 处理 WebSocket 连接管理错误（注册、注销、发送失败）。
      * 在 `handleActionExecution` 中使用带超时的 `context.Context`。
      * 使用 `defer` 和 `recover` (可选) 增加稳定性。
  * **`MentisExecutor`:**
      * 使用 `logging` 记录详细日志。
      * 在 Action Handlers 中使用 `try...except` 捕获执行错误。
      * 将捕获到的错误通过 `push_observation` 发送 `ErrorObservation`。
      * 处理 `subprocess` 异常 (`FileNotFoundError`, 权限问题)。
      * 处理 `jupyter_client` 通信异常和超时。
      * 处理推送 Observation 时的 `httpx` 网络异常。
      * 确保异步任务（如读写流）被正确管理和取消。

-----

## 9\. 测试策略

  * **单元测试:**
      * `MentisRuntime`: 测试 Manager 的状态转换、Docker 命令模拟、Hub 的注册/广播逻辑。
      * `MentisExecutor`: 测试每个 Action Handler 的逻辑（可能需要模拟 subprocess 和 jupyter\_client）。测试 Observation 推送。
  * **集成测试:**
      * 启动 `MentisRuntime` 和 Docker。
      * 编写测试脚本 (使用 `mentis_client`)：
          * 创建沙盒。
          * 连接 WebSocket/SSE 流。
          * 执行 `run_shell_command` (e.g., `echo hello && sleep 2 && echo world && exit 1`)。
          * **验证:** 是否收到了 `CmdStartObservation`, 包含 "hello" 和 "world" 的 `CmdOutputObservationPart`, 以及包含 `exit_code: 1` 的 `CmdEndObservation`。
          * 执行 `run_ipython_cell` (e.g., `import time; print(1); time.sleep(1); print(2); 1/0`)。
          * **验证:** 是否收到了 `IPythonStartObservation`, 包含 1 和 2 的 `IPythonOutputObservationPart`, 以及包含 `status: 'error'` 和 traceback 的 `IPythonResultObservation`。
          * 测试并发执行。
          * 测试删除沙盒。
