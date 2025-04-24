// Filepath: app/page.tsx (Corrected with Dynamic Import)
'use client'; // Mark as client component

import React, { useState, useCallback, useRef, useEffect } from 'react';
import dynamic from 'next/dynamic'; // <-- 1. 导入 dynamic
import DebugView from '@/components/DebugView';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";

// --- 2. 动态导入 TerminalComponent，并禁用 SSR ---
const TerminalComponent = dynamic(() => import('@/components/TerminalComponent'), {
  ssr: false, // <--- 关键：禁止服务器端渲染
  loading: () => <div className="w-full h-full flex items-center justify-center bg-black text-white"><p>Loading Terminal...</p></div> // 可选的加载状态
});
// --- 结束动态导入 ---

export default function HomePage() {
  const [sandboxId, setSandboxId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [debugLogs, setDebugLogs] = useState<string[]>(['Debug view initialized.']);
  // webSocketRef 不再需要在这里管理，由 TerminalComponent 内部管理

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
      setIsConnected(true); // Assume connection attempt starts, TerminalComponent handles actual state
    } else {
      addLog("Please enter a Sandbox ID.");
    }
  }, [inputValue, addLog]);

  // 处理断开连接按钮点击
  const handleDisconnect = useCallback(() => {
     addLog("Disconnect button clicked. Triggering disconnect.");
     setSandboxId(null); // Setting ID to null triggers disconnect in TerminalComponent
     setIsConnected(false); // Update UI state immediately
  }, [addLog]);


  // --- 发送命令到 Next.js API 代理 ---
  const handleSendCommand = useCallback(async (command: string, type: 'shell' | 'ipython') => {
    if (!sandboxId) {
        addLog("Cannot send command: Not connected to a sandbox.");
        // Optionally re-prompt in terminal? TerminalComponent handles its prompt.
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


  // Note: Connection status (isConnected) is simplified here.
  // A robust solution would involve TerminalComponent emitting status changes
  // back to this parent component via a callback prop.
  useEffect(() => {
      setIsConnected(!!sandboxId);
  }, [sandboxId]);


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
            disabled={isConnected} // Disable input when connected
            className="w-64"
          />
          <Button onClick={handleConnect} disabled={isConnected || !inputValue}>
            Connect
          </Button>
          <Button onClick={handleDisconnect} disabled={!isConnected} variant="destructive">
            Disconnect
          </Button>
          <span className={`ml-4 px-3 py-1 rounded text-sm font-medium ${isConnected ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'}`}>
            Status: {isConnected ? 'Connected (Attempting)' : 'Disconnected'}
          </span>
        </CardContent>
      </Card>

      {/* --- Terminal --- */}
      <div className="flex-grow min-h-0 border rounded-md overflow-hidden shadow-sm"> {/* Added border/styling */}
          {/* Render TerminalComponent only when sandboxId is set to trigger connection */}
          {/* The component itself handles the ws connection based on the prop */}
          <TerminalComponent
              key={sandboxId} // Force re-mount on ID change if needed, might not be necessary
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