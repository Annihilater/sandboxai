使用 Next.js + React + TailwindCSS/shadcn 来构建这个示例是一个绝佳的选择，它能提供良好的开发体验、现代化的 UI，并且能轻松解决跨域问题。

我将为你生成这个示例的核心代码文件。这个示例将包含：

1.  一个使用 `xterm.js` 的 React 组件来模拟终端。
2.  一个输入框用于输入 Sandbox ID 并连接 WebSocket。
3.  一个简单的调试视图区域，用于显示连接状态和收到的原始 WebSocket 消息。
4.  一个 Next.js API 路由作为代理，用于将前端发送的命令请求转发给 Go Runtime，从而解决 CORS 问题。
5.  使用 `shadcn/ui` 组件和 TailwindCSS 实现基本布局和样式。

**前提:**

* 你需要有一个 Node.js 环境 (v18 或更高版本)。
* 你需要使用 `npx create-next-app@latest --typescript --tailwind your-project-name` 初始化一个新的 Next.js 项目（选择使用 App Router）。
* 在项目根目录下，你需要使用 `npx shadcn-ui@latest init` 初始化 `shadcn/ui`，并按需添加几个组件（如 `button`, `input`, `card`）。
* 你需要安装 `xterm` 和相关插件：`npm install xterm xterm-addon-fit` 或 `yarn add xterm xterm-addon-fit`。

**文件结构 (简化):**

```
web_demo/
├── app/
│   ├── page.tsx              # 主页面 UI
│   └── api/
│       └── sandbox/
│           └── execute/
│               └── route.ts  # Next.js API 代理路由
├── components/
│   ├── ui/                   # shadcn/ui 生成的组件
│   ├── TerminalComponent.tsx # Xterm.js 组件
│   └── DebugView.tsx         # 调试视图组件
├── lib/
│   └── utils.ts              # shadcn/ui 工具文件
├── globals.css               # Tailwind 全局样式
├── tailwind.config.ts
├── next.config.mjs
├── package.json
└── tsconfig.json
```

---

**代码实现:**

**1. Next.js API Route Proxy (`app/api/sandbox/execute/route.ts`)**

这个文件处理前端发送过来的命令执行请求，并将其转发给 Go Runtime。

```typescript
// Filepath: app/api/sandbox/execute/route.ts
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// 从环境变量或配置中获取 Go Runtime 的基础 URL
// 注意：这是服务器端代码，不能访问浏览器的 window.location
// 最好在 .env.local 文件中定义 MENTIS_RUNTIME_API_URL=http://127.0.0.1:5266
const runtimeApiUrl = process.env.MENTIS_RUNTIME_API_URL || 'http://127.0.0.1:5266';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { sandboxId, command, type } = body; // type 可以是 'shell' 或 'ipython'

    if (!sandboxId || !command || !type) {
      return NextResponse.json({ error: 'Missing sandboxId, command, or type' }, { status: 400 });
    }

    let endpoint = '';
    let payload: Record<string, string> = {};

    // 根据类型构造目标 URL 和 Payload
    if (type === 'shell') {
      endpoint = `/v1/spaces/default/sandboxes/${sandboxId}/tools:run_shell_command`;
      payload = { command: command };
    } else if (type === 'ipython') {
      endpoint = `/v1/spaces/default/sandboxes/${sandboxId}/tools:run_ipython_cell`;
      payload = { code: command }; // IPython 使用 'code' 字段
    } else {
      return NextResponse.json({ error: 'Invalid type specified' }, { status: 400 });
    }

    const targetUrl = `${runtimeApiUrl}${endpoint}`;
    console.log(`Proxying ${type} command to: ${targetUrl}`);

    // 使用 fetch 将请求转发给 Go Runtime
    const backendResponse = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // 如果 Go Runtime 需要认证，在这里添加 Authorization 头
      },
      body: JSON.stringify(payload),
      // 设置合理的超时
      // 注意：node-fetch (Next.js 默认使用) 可能需要不同方式设置超时
    });

    // 将 Go Runtime 的响应状态和内容返回给前端
    const data = await backendResponse.json();

    if (!backendResponse.ok) {
        // 如果后端返回错误，将其转发给前端
        console.error(`Backend error (Status ${backendResponse.status}):`, data);
        return NextResponse.json(data || { error: 'Backend request failed' }, { status: backendResponse.status });
    }

    // 返回成功响应 (包含 action_id)
    return NextResponse.json(data, { status: backendResponse.status }); // 通常是 202

  } catch (error) {
    console.error('Error in API proxy route:', error);
    let errorMessage = 'Internal Server Error';
    if (error instanceof Error) {
        errorMessage = error.message;
    }
    return NextResponse.json({ error: 'Proxy request failed', details: errorMessage }, { status: 500 });
  }
}
```

**2. Debug View Component (`components/DebugView.tsx`)**

一个简单的组件，用于显示日志或状态信息。

```typescript
// Filepath: components/DebugView.tsx
import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"; // 假设你已添加 card 组件
import { ScrollArea } from "@/components/ui/scroll-area"; // 假设你已添加 scroll-area 组件

interface DebugViewProps {
  logs: string[];
}

const DebugView: React.FC<DebugViewProps> = ({ logs }) => {
  return (
    <Card className="w-full h-[200px] flex flex-col"> {/* 设置固定高度或相对高度 */}
      <CardHeader className="p-4 border-b">
        <CardTitle className="text-lg">Debug Log / Raw Observations</CardTitle>
      </CardHeader>
      <CardContent className="p-0 flex-grow"> {/* 让内容区域填充 */}
        <ScrollArea className="h-full p-4"> {/* 设置 ScrollArea 高度 */}
          <pre className="text-xs whitespace-pre-wrap break-all">
            {logs.map((log, index) => (
              <div key={index}>{log}</div>
            ))}
          </pre>
        </ScrollArea>
      </CardContent>
    </Card>
  );
};

export default DebugView;
```

**3. Terminal Component (`components/TerminalComponent.tsx`)**

封装 `xterm.js` 的核心逻辑。

```typescript
// Filepath: components/TerminalComponent.tsx
'use client'; // 标记为客户端组件

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

interface TerminalComponentProps {
  sandboxId: string | null;
  onCommand: (command: string, type: 'shell' | 'ipython') => Promise<void>; // 用于发送命令的回调
  onLog: (message: string) => void; // 用于记录日志到 DebugView
}

const TerminalComponent: React.FC<TerminalComponentProps> = ({ sandboxId, onCommand, onLog }) => {
  const terminalRef = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fitAddon = useRef<FitAddon | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const commandHistory = useRef<string[]>([]);
  const historyIndex = useRef<number>(-1);
  const currentLine = useRef<string>('');

  // --- 清理 WebSocket ---
  const cleanupWebSocket = useCallback(() => {
    if (ws.current) {
      onLog('Closing WebSocket connection...');
      ws.current.close();
      ws.current = null;
    }
  }, [onLog]);

  // --- WebSocket 连接 ---
  const connectWebSocket = useCallback(() => {
    if (!sandboxId) {
      onLog('Cannot connect: Sandbox ID is missing.');
      return;
    }
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      onLog('WebSocket already connected.');
      return;
    }

    cleanupWebSocket(); //确保旧连接已关闭

    const wsUrl = `ws://${window.location.hostname || 'localhost'}:5266/v1/sandboxes/${sandboxId}/stream`;
    onLog(`Attempting to connect WebSocket: ${wsUrl}`);
    term.current?.writeln(`\r\n\x1b[1;34mINFO: Connecting WebSocket to ${wsUrl}...\x1b[0m`);

    try {
        ws.current = new WebSocket(wsUrl);

        ws.current.onopen = () => {
            onLog('WebSocket Connected!');
            term.current?.writeln(`\r\n\x1b[1;32mINFO: WebSocket Connected to Sandbox ${sandboxId}!\x1b[0m`);
            prompt();
        };

        ws.current.onmessage = (event) => {
            // console.log("Raw WS message:", event.data); // Debugging raw data
            onLog(`WS MSG: ${event.data.substring(0, 200)}...`); // Log to debug view
            try {
                const obs = JSON.parse(event.data);
                const obsType = obs.observation_type;
                const line = obs.line;
                const streamType = obs.stream;

                if (obsType === 'stream' && line !== null && line !== undefined) {
                    // 写入终端，确保换行正确
                    term.current?.write(line.replace(/\r\n|\n|\r/g, '\r\n'));
                    // 如果 stream 消息本身不保证以换行结束，可能需要手动添加
                    // if (!line.endsWith('\n')) {
                    //    term.current?.write('\r\n');
                    // }
                } else if (obsType === 'result') {
                    const exitCode = obs.exit_code;
                    // Check multiple possible error fields from different models/versions
                    const error = obs.error || obs.error_value || (obs.error_name ? `${obs.error_name}: ${obs.error_value}`: null);
                    if (exitCode !== 0 || error) {
                        term.current?.writeln(`\r\n\x1b[1;31m[Command finished with Exit Code: ${exitCode}, Error: ${error || 'N/A'}]\x1b[0m`);
                    } else {
                        term.current?.writeln(`\r\n\x1b[1;32m[Command finished successfully (Exit Code: ${exitCode})]\x1b[0m`);
                    }
                } else if (obsType === 'end') {
                    // 收到 end 后显示提示符
                    prompt();
                } else if (obsType === 'error') {
                     term.current?.writeln(`\r\n\x1b[1;31m[System Error: ${obs.message || JSON.stringify(obs)}]\x1b[0m`);
                     prompt(); // 也显示提示符
                } else if (obsType === 'start') {
                     term.current?.writeln(`\x1b[36m[Action started: ${obs.action_id}]\x1b[0m`);
                }

            } catch (e) {
                console.error("Failed to parse WebSocket message:", e);
                onLog(`ERROR parsing message: ${event.data}`);
                term.current?.writeln(`\r\n\x1b[1;31mERROR: Received unparseable message\x1b[0m`);
            }
        };

        ws.current.onerror = (error) => {
            console.error("WebSocket Error:", error);
            onLog(`ERROR: WebSocket connection error. See browser console.`);
            term.current?.writeln(`\r\n\x1b[1;31mERROR: WebSocket connection error.\x1b[0m`);
        };

        ws.current.onclose = (event) => {
            onLog(`WebSocket disconnected. Code: ${event.code}, Reason: ${event.reason || 'N/A'}`);
            term.current?.writeln(`\r\n\x1b[1;33mINFO: WebSocket disconnected.\x1b[0m`);
            ws.current = null;
            // Optionally try to reconnect or update UI status
        };
    } catch (err) {
        onLog(`ERROR creating WebSocket: ${err}`);
        term.current?.writeln(`\r\n\x1b[1;31mERROR: Could not create WebSocket connection.\x1b[0m`);
    }

  }, [sandboxId, onLog, cleanupWebSocket]); // Dependencies for connectWebSocket

  // --- 初始化和效果 ---
  useEffect(() => {
    if (terminalRef.current && !term.current) {
      console.log("Initializing Xterm");
      term.current = new Terminal({ cursorBlink: true, convertEol: true }); // convertEol helps with line endings
      fitAddon.current = new FitAddon();
      term.current.loadAddon(fitAddon.current);
      term.current.open(terminalRef.current);
      fitAddon.current.fit();

      // --- 输入处理 ---
      let lineBuffer = '';
      term.current.onData(data => {
          const code = data.charCodeAt(0);
          // console.log("Key code:", code, "Data:", data); // Debug keys

          if (code === 13) { // Enter key
              if (lineBuffer.trim()) {
                   term.current?.writeln(''); // Move to next line in terminal
                   commandHistory.current.push(lineBuffer); // Add to history
                   historyIndex.current = commandHistory.current.length; // Reset history index

                   // 决定类型并调用父组件的回调
                   const commandToSend = lineBuffer;
                   const type = commandToSend.startsWith('!') ? 'shell' : 'ipython';
                   const actualCommand = type === 'shell' ? commandToSend.substring(1).trim() : commandToSend;
                   onCommand(actualCommand, type); // 发送命令

                   lineBuffer = ''; // 清空缓冲区
              } else {
                   // If empty line submitted, just show prompt again
                   term.current?.writeln('');
                   prompt();
              }
          } else if (code === 127 || code === 8) { // Backspace (DEL or BS)
              if (lineBuffer.length > 0) {
                  term.current?.write('\b \b'); // Standard backspace effect
                  lineBuffer = lineBuffer.slice(0, -1);
              }
          } else if (code === 27) { // Escape sequences (like arrow keys)
              // Handle arrow keys for history (simple version)
              const sequence = data.substring(1); // Get sequence after ESC
              if (sequence === '[A') { // Up arrow
                 if (historyIndex.current > 0) {
                      historyIndex.current--;
                      const prevCommand = commandHistory.current[historyIndex.current];
                      // Clear current line and write history command
                      term.current?.write('\r\x1b[K$ ' + prevCommand); // \r=CR, \x1b[K=clear line
                      lineBuffer = prevCommand;
                 }
              } else if (sequence === '[B') { // Down arrow
                  if (historyIndex.current < commandHistory.current.length - 1) {
                      historyIndex.current++;
                      const nextCommand = commandHistory.current[historyIndex.current];
                      term.current?.write('\r\x1b[K$ ' + nextCommand);
                      lineBuffer = nextCommand;
                  } else if (historyIndex.current === commandHistory.current.length - 1) {
                      // If at the end, clear line
                      historyIndex.current++;
                      term.current?.write('\r\x1b[K$ ');
                      lineBuffer = "";
                  }
              }
              // Ignore other escape sequences for simplicity
          } else if (code >= 32 && code <= 126) { // Printable ASCII characters
              lineBuffer += data;
              term.current?.write(data); // Echo printable character
          } else {
              console.log("Ignoring non-printable character, code:", code);
          }
      });

      // --- 调整大小 ---
      const resizeObserver = new ResizeObserver(() => {
          fitAddon.current?.fit();
      });
      if (terminalRef.current) {
          resizeObserver.observe(terminalRef.current);
      }

      // --- 初始提示符 ---
      term.current?.writeln('Terminal initialized. Connect to a sandbox.');

      // --- 清理 ---
      return () => {
          resizeObserver.disconnect();
          term.current?.dispose();
          term.current = null;
          cleanupWebSocket();
      };
    }
  }, [onCommand, cleanupWebSocket]); // Effect for initialization runs once


  // --- Effect for connecting/disconnecting when sandboxId changes ---
  useEffect(() => {
    if (sandboxId && term.current) {
      connectWebSocket();
    } else {
      cleanupWebSocket();
      if(term.current) {
          term.current.writeln('\r\n\x1b[1;33mINFO: Disconnected. Please enter a Sandbox ID and connect.\x1b[0m');
      }
    }
    // Cleanup on sandboxId change or unmount
    return cleanupWebSocket;
  }, [sandboxId, connectWebSocket, cleanupWebSocket]); // Dependencies


  // --- 显示提示符 ---
  const prompt = () => {
      currentLine.current = ''; // Clear buffer on new prompt
      term.current?.write('\r\n$ ');
  };


  return <div id="terminal" ref={terminalRef} className="w-full h-full bg-black text-white p-2"></div>;
};

export default TerminalComponent;

```

**4. Main Page Component (`app/page.tsx`)**

这个文件设置页面布局，包含输入框、按钮、终端组件和调试视图。

```typescript
// Filepath: app/page.tsx
'use client'; // Mark as client component

import React, { useState, useCallback, useRef } from 'react';
import TerminalComponent from '@/components/TerminalComponent';
import DebugView from '@/components/DebugView';
import { Button } from "@/components/ui/button"; // from shadcn/ui
import { Input } from "@/components/ui/input";   // from shadcn/ui
import { Card, CardContent } from "@/components/ui/card"; // from shadcn/ui

export default function HomePage() {
  const [sandboxId, setSandboxId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [debugLogs, setDebugLogs] = useState<string[]>(['Debug view initialized.']);
  const webSocketRef = useRef<WebSocket | null>(null); // To manage WS instance status

  // 回调函数，用于将日志添加到 DebugView
  const addLog = useCallback((message: string) => {
    console.log("Adding log:", message); // Also log to console
    setDebugLogs(prevLogs => [
        `[${new Date().toLocaleTimeString()}] ${message}`,
         ...prevLogs // Add new log to the top
        ].slice(0, 100) // Keep last 100 logs
    );
  }, []);

  // 处理连接按钮点击
  const handleConnect = useCallback(() => {
    if (inputValue) {
      addLog(`Setting Sandbox ID and attempting connection: ${inputValue}`);
      setSandboxId(inputValue); // This will trigger the TerminalComponent's useEffect to connect
    } else {
      addLog("Please enter a Sandbox ID.");
    }
  }, [inputValue, addLog]);

  // 处理断开连接按钮点击 (实际上由 TerminalComponent 内部管理)
  // 这里只是更新 UI 状态
  const handleDisconnect = useCallback(() => {
     addLog("Disconnect button clicked. Triggering disconnect.");
     setSandboxId(null); // Setting ID to null triggers disconnect in TerminalComponent
  }, [addLog]);


  // --- 发送命令到 Next.js API 代理 ---
  const handleSendCommand = useCallback(async (command: string, type: 'shell' | 'ipython') => {
    if (!sandboxId) {
        addLog("Cannot send command: Not connected to a sandbox.");
        return;
    }
    addLog(`Sending ${type} command via API proxy: ${command.substring(0, 50)}...`);

    try {
        const response = await fetch('/api/sandbox/execute', { // Call the Next.js API route
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                sandboxId: sandboxId,
                command: command,
                type: type,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            addLog(`ERROR sending command (HTTP ${response.status}): ${data.error || JSON.stringify(data)}`);
        } else {
            addLog(`Command accepted by server. Action ID: ${data.action_id}`);
        }
    } catch (error) {
        let errorMsg = 'Unknown error';
        if (error instanceof Error) errorMsg = error.message;
        console.error("Error sending command via proxy:", error);
        addLog(`NETWORK ERROR sending command: ${errorMsg}`);
    }
  }, [sandboxId, addLog]);


  // Update connection status based on WebSocket state (could be improved with callbacks)
  // This is a simple example; a more robust way involves callbacks from TerminalComponent
  useEffect(() => {
      // Placeholder: In a real app, TerminalComponent would likely call back
      // to update the parent's `isConnected` state via props/context.
      // For this example, we infer based on sandboxId presence.
      setIsConnected(!!sandboxId);
      if (!sandboxId) {
          addLog("UI: Sandbox ID cleared, assuming disconnected.");
      }
  }, [sandboxId, addLog]);


  return (
    <div className="flex flex-col h-screen p-4 bg-gray-100 dark:bg-gray-900 space-y-4">
      <h1 className="text-2xl font-bold text-center text-gray-800 dark:text-gray-200">Mentis Sandbox Web Example</h1>

      {/* --- Controls --- */}
      <Card>
        <CardContent className="p-4 flex flex-wrap items-center gap-4">
          <label htmlFor="sandboxIdInput" className="font-medium text-gray-700 dark:text-gray-300">
            Sandbox ID:
          </label>
          <Input
            id="sandboxIdInput"
            type="text"
            placeholder="Enter Sandbox ID"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isConnected}
            className="w-64"
          />
          <Button onClick={handleConnect} disabled={isConnected || !inputValue}>
            Connect
          </Button>
          <Button onClick={handleDisconnect} disabled={!isConnected} variant="destructive">
            Disconnect
          </Button>
          <span className={`ml-4 px-3 py-1 rounded ${isConnected ? 'bg-green-200 text-green-800' : 'bg-red-200 text-red-800'}`}>
            Status: {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </CardContent>
      </Card>

      {/* --- Terminal --- */}
      <div className="flex-grow min-h-0"> {/* Allow terminal to take remaining height */}
          {/* Pass null sandboxId initially, update on connect */}
          <TerminalComponent
              sandboxId={sandboxId}
              onCommand={handleSendCommand}
              onLog={addLog}
          />
      </div>


      {/* --- Debug View --- */}
      <div className="flex-shrink-0 h-[220px]"> {/* Give DebugView fixed height */}
          <DebugView logs={debugLogs} />
      </div>

    </div>
  );
}
```

**如何运行:**

1.  **设置项目:** 确保你有一个配置好 TypeScript 和 Tailwind 的 Next.js 项目，并且已经初始化并安装了 `shadcn/ui` 的 `button`, `input`, `card`, `scroll-area` 组件。同时安装 `xterm` 和 `xterm-addon-fit`。
2.  **创建文件:** 将上面的代码分别保存到对应的路径 (`app/page.tsx`, `components/TerminalComponent.tsx`, `components/DebugView.tsx`, `app/api/sandbox/execute/route.ts`)。
3.  **环境变量 (可选但推荐):** 在项目根目录创建 `.env.local` 文件，并添加 Go Runtime 的地址：
    ```
    MENTIS_RUNTIME_API_URL=http://127.0.0.1:5266
    ```
4.  **启动 Go Runtime:** 确保你的 Go Mentis Runtime 服务正在运行。
5.  **启动 Next.js 开发服务器:**
    ```bash
    npm run dev
    # 或者
    yarn dev
    ```
6.  **访问:** 在浏览器中打开 Next.js 应用的地址 (通常是 `http://localhost:3000`)。
7.  **使用:** 按照页面上的说明创建沙箱（使用 `curl`），将 Sandbox ID 粘贴到输入框，点击 Connect，然后在终端中输入命令（Shell 命令前加 `!`）。

这个示例提供了一个基础但可用的框架，你可以根据需要进一步扩展和美化。