// Filepath: app/page.tsx
'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import dynamic from 'next/dynamic';
import DebugView from '@/components/DebugView';
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const TerminalComponent = dynamic(() => import('@/components/TerminalComponent'), {
  ssr: false,
  loading: () => <div className="w-full h-full flex items-center justify-center bg-black text-white"><p>Loading Terminal...</p></div>
});

interface Sandbox {
  id: string;
  isRunning: boolean;
  agentUrl: string;
  containerId: string;
}

export default function HomePage() {
  const [sandboxId, setSandboxId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [debugLogs, setDebugLogs] = useState<string[]>(['Debug view initialized.']);
  const [sandboxes, setSandboxes] = useState<Sandbox[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const addLog = useCallback((message: string) => {
    console.log("Adding log:", message);
    setDebugLogs(prevLogs => [
      `[${new Date().toLocaleTimeString()}] ${message}`,
      ...prevLogs
    ].slice(0, 100));
  }, []);

  const handleCommand = useCallback(async (command: string, type: 'shell' | 'ipython') => {
    if (!sandboxId) {
      addLog("Cannot send command: Not connected to a sandbox.");
      return;
    }
    addLog(`Sending ${type} command via API proxy: ${command.substring(0, 50)}...`);

    try {
      const response = await fetch('/api/sandbox/execute', {
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

  const fetchSandboxes = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await fetch('/api/sandbox/list');
      if (!response.ok) {
        throw new Error('Failed to fetch sandboxes');
      }
      const data = await response.json();
      setSandboxes(data.sandboxes);
      addLog(`Fetched ${data.sandboxes.length} sandboxes`);
    } catch (error) {
      console.error('Error fetching sandboxes:', error);
      addLog(`Error fetching sandboxes: ${error}`);
    } finally {
      setIsLoading(false);
    }
  }, [addLog]);

  const handleCreateSandbox = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await fetch('/api/sandbox/create', {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error('Failed to create sandbox');
      }
      const data = await response.json();
      addLog(`Created new sandbox: ${data.id}`);
      await fetchSandboxes();
      setSandboxId(data.id);
      setIsConnected(true);
    } catch (error) {
      console.error('Error creating sandbox:', error);
      addLog(`Error creating sandbox: ${error}`);
    } finally {
      setIsLoading(false);
    }
  }, [addLog, fetchSandboxes]);

  const handleSelectSandbox = useCallback((id: string) => {
    console.log('Selected sandbox:', id);
    setSandboxId(id);
    setIsConnected(true);
    addLog(`Selected sandbox: ${id}`);
  }, [addLog]);

  const handleDisconnect = useCallback(() => {
    addLog("Disconnect button clicked. Triggering disconnect.");
    setSandboxId(null);
    setIsConnected(false);
  }, [addLog]);

  useEffect(() => {
    fetchSandboxes();
  }, [fetchSandboxes]);

  return (
    <div className="flex flex-col h-screen bg-slate-50 p-4 space-y-4">
      <div className="flex-1 flex space-x-4 min-h-0">
        <div className="w-[400px] flex flex-col space-y-4">
          <Card className="flex-1 shadow-lg border-slate-200">
            <CardHeader className="pb-3 space-y-1.5">
              <CardTitle className="text-xl font-semibold text-slate-800">Sandbox Control</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                <div className="flex flex-col space-y-4">
                  <div className="grid grid-cols-5 gap-2">
                    <Button 
                      onClick={handleCreateSandbox}
                      disabled={isLoading}
                      className="col-span-4 bg-blue-600 hover:bg-blue-700 text-white font-medium shadow-sm"
                    >
                      {isLoading ? 'Creating...' : 'Create New Sandbox'}
                    </Button>
                    <Button 
                      onClick={fetchSandboxes}
                      disabled={isLoading}
                      variant="outline"
                      className="border-slate-200 hover:bg-slate-50 shadow-sm text-slate-600"
                      title="Refresh sandbox list"
                    >
                      ↻
                    </Button>
                  </div>
                  
                  <div className="space-y-2.5">
                    <label className="text-sm font-semibold text-slate-700">Select Sandbox</label>
                    <Select
                      value={sandboxId || ''}
                      onValueChange={handleSelectSandbox}
                    >
                      <SelectTrigger 
                        className="w-full bg-white border-slate-200 shadow-sm hover:border-slate-300 transition-colors"
                      >
                        <SelectValue placeholder="Select a sandbox" />
                      </SelectTrigger>
                      <SelectContent 
                        className="bg-white border border-slate-200 shadow-lg max-h-[300px] w-[400px] overflow-hidden"
                        position="popper"
                        sideOffset={4}
                      >
                        <div className="p-1">
                          {sandboxes.map((sandbox) => (
                            <SelectItem 
                              key={sandbox.id} 
                              value={sandbox.id}
                              disabled={!sandbox.isRunning}
                              className="hover:bg-slate-50 focus:bg-slate-50 cursor-pointer rounded-md mb-1 last:mb-0"
                            >
                              <div className="flex flex-col py-2 px-1">
                                <div className="flex items-center space-x-2">
                                  <span className={`w-2 h-2 rounded-full ${
                                    sandbox.isRunning 
                                      ? 'bg-green-500' 
                                      : 'bg-red-500'
                                  }`} />
                                  <span className="font-mono text-sm truncate flex-1">{sandbox.id}</span>
                                </div>
                                <div className="mt-1 flex items-center space-x-2">
                                  <span className={`text-xs font-medium ${
                                    sandbox.isRunning 
                                      ? 'text-green-600' 
                                      : 'text-red-600'
                                  }`}>
                                    {sandbox.isRunning ? 'Running' : 'Stopped'}
                                  </span>
                                  <span className="text-xs text-slate-400">
                                    {sandbox.containerId}
                                  </span>
                                </div>
                              </div>
                            </SelectItem>
                          ))}
                        </div>
                      </SelectContent>
                    </Select>
                  </div>

                  <Button 
                    onClick={handleDisconnect}
                    disabled={!isConnected}
                    variant="destructive"
                    className="w-full bg-red-500 hover:bg-red-600 disabled:bg-slate-100 disabled:text-slate-400 shadow-sm font-medium"
                  >
                    Disconnect
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="flex-1 flex flex-col space-y-4 min-w-0">
          <Card className="flex-1 shadow-lg border-slate-200 overflow-hidden">
            <CardHeader className="pb-3 border-b border-slate-100">
              <CardTitle className="text-xl font-semibold text-slate-800">Terminal</CardTitle>
            </CardHeader>
            <CardContent className="p-0 h-[calc(100%-4rem)]">
              <TerminalComponent 
                sandboxId={sandboxId}
                onCommand={handleCommand}
                onLog={addLog}
              />
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="h-[280px]">
        <Card className="h-full shadow-lg border-slate-200">
          <CardHeader className="pb-3 border-b border-slate-100">
            <CardTitle className="text-xl font-semibold text-slate-800">Debug Logs</CardTitle>
          </CardHeader>
          <CardContent className="h-[calc(100%-4rem)] p-0">
            <DebugView logs={debugLogs} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}