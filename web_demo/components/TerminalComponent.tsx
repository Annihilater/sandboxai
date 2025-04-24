// Filepath: components/TerminalComponent.tsx
'use client'; // 标记为客户端组件

import React, { useEffect, useRef, useState, useCallback } from 'react';
// --- xterm imports will be done dynamically ---
// import { Terminal } from 'xterm';
// import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

// --- Define types dynamically loaded modules will conform to ---
type XtermTerminal = import('xterm').Terminal;
type XtermFitAddon = import('xterm-addon-fit').FitAddon;

interface TerminalComponentProps {
  sandboxId: string | null;
  onCommand: (command: string, type: 'shell' | 'ipython') => Promise<void>; // 用于发送命令的回调
  onLog: (message: string) => void; // 用于记录日志到 DebugView
}

const TerminalComponent: React.FC<TerminalComponentProps> = ({ sandboxId, onCommand, onLog }) => {
  const terminalRef = useRef<HTMLDivElement>(null);
  const term = useRef<XtermTerminal | null>(null);
  const fitAddon = useRef<XtermFitAddon | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const commandHistory = useRef<string[]>([]);
  const historyIndex = useRef<number>(-1);
  const currentCommand = useRef<string>('');
  const [isClient, setIsClient] = useState(false);
  const resizeObserverRef = useRef<ResizeObserver | null>(null); // Ref for ResizeObserver

  useEffect(() => {
    setIsClient(true);
  }, []);

  const cleanupWebSocket = useCallback(() => {
    if (ws.current) {
      onLog('Closing WebSocket connection...');
      ws.current.close();
      ws.current = null;
    }
  }, [onLog]);

  // --- Display prompt function ---
  const prompt = useCallback(() => {
    if (term.current) {
      term.current.write('\r\n$ ');
    }
  }, []); // No dependencies needed if it only uses refs

  const connectWebSocket = useCallback(() => {
    if (!sandboxId) {
      onLog('Cannot connect: Sandbox ID is missing.');
      return;
    }

    cleanupWebSocket();

    const wsUrl = `ws://${window.location.hostname || 'localhost'}:5266/v1/sandboxes/${sandboxId}/stream`;
    onLog(`Attempting to connect WebSocket: ${wsUrl}`);
    
    if (term.current) {
      term.current.writeln(`\r\n\x1b[1;34mINFO: Connecting WebSocket to ${wsUrl}...\x1b[0m`);
    }

    try {
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        onLog('WebSocket Connected!');
        if (term.current) {
          term.current.writeln(`\r\n\x1b[1;32mINFO: WebSocket Connected to Sandbox ${sandboxId}!\x1b[0m`);
          prompt();
        }
      };

      ws.current.onmessage = (event) => {
        try {
          const obs = JSON.parse(event.data);
          if (term.current) {
            const obsType = obs.observation_type;
            const line = obs.line;

            if (obsType === 'stream' && line !== null && line !== undefined) {
              term.current.write(line.replace(/\r\n|\n|\r/g, '\r\n'));
            } else if (obsType === 'result') {
              const exitCode = obs.exit_code;
              const error = obs.error || obs.error_value || (obs.error_name ? `${obs.error_name}: ${obs.error_value}` : null);
              if (exitCode !== 0 || error) {
                term.current.writeln(`\r\n\x1b[1;31m[Command finished with Exit Code: ${exitCode}, Error: ${error || 'N/A'}]\x1b[0m`);
              } else {
                term.current.writeln(`\r\n\x1b[1;32m[Command finished successfully (Exit Code: ${exitCode})]\x1b[0m`);
              }
              prompt();
            } else if (obsType === 'end') {
              term.current.writeln(`\x1b[1;34m[Action finished]\x1b[0m`);
              prompt();
            } else if (obsType === 'error') {
              term.current.writeln(`\r\n\x1b[1;31m[System Error: ${obs.message || JSON.stringify(obs)}]\x1b[0m`);
              prompt();
            } else if (obsType === 'start') {
              term.current.writeln(`\x1b[36m[Action started: ${obs.action_id}]\x1b[0m`);
            }
          }
        } catch (error) {
          console.error('Error processing WebSocket message:', error);
        }
      };

      ws.current.onclose = () => {
        onLog('WebSocket connection closed.');
        if (term.current) {
          term.current.writeln('\r\n\x1b[1;31mINFO: WebSocket connection closed.\x1b[0m');
        }
      };

      ws.current.onerror = (error) => {
        onLog(`WebSocket error: ${error}`);
        if (term.current) {
          term.current.writeln('\r\n\x1b[1;31mERROR: WebSocket connection error.\x1b[0m');
        }
      };
    } catch (error) {
      console.error('Error creating WebSocket:', error);
      onLog(`Error creating WebSocket: ${error}`);
    }
  }, [sandboxId, onLog, cleanupWebSocket, prompt]);

  // --- Initialization Effect (Client-side only) ---
  useEffect(() => {
    if (isClient && terminalRef.current && !term.current) {
      let resizeObserver: ResizeObserver | null = null; // Define here for cleanup access

      Promise.all([
          import('xterm'),
          import('xterm-addon-fit')
      ]).then(([{ Terminal }, { FitAddon }]) => {
          if (!terminalRef.current) return; // Check if component unmounted before promise resolved

          console.log("Initializing Xterm on client-side");
          const localTerm = new Terminal({ cursorBlink: true, convertEol: true });
          const localFitAddon = new FitAddon();
          localTerm.loadAddon(localFitAddon);
          localTerm.open(terminalRef.current);
          localFitAddon.fit();

          term.current = localTerm;
          fitAddon.current = localFitAddon;

          // --- Input handling ---
          let lineBuffer = '';
          localTerm.onData((data: string) => { // Added type annotation for data
              const code = data.charCodeAt(0);

              if (code === 13) { // Enter
                  if (lineBuffer.trim()) {
                       localTerm.writeln('');
                       commandHistory.current.push(lineBuffer);
                       historyIndex.current = commandHistory.current.length;

                       const commandToSend = lineBuffer;
                       const type = commandToSend.startsWith('!') ? 'shell' : 'ipython';
                       const actualCommand = type === 'shell' ? commandToSend.substring(1).trim() : commandToSend;
                       onCommand(actualCommand, type);

                       lineBuffer = '';
                  } else {
                       localTerm.writeln('');
                       prompt();
                  }
              } else if (code === 127 || code === 8) { // Backspace
                  if (lineBuffer.length > 0) {
                      localTerm.write('\x08 \x08'); // Use hex escape for backspace
                      lineBuffer = lineBuffer.slice(0, -1);
                  }
              } else if (code === 27) { // Escape sequences (Arrows)
                  const sequence = data.substring(1);
                  if (sequence === '[A') { // Up
                     if (historyIndex.current > 0) {
                          historyIndex.current--;
                          const prevCommand = commandHistory.current[historyIndex.current];
                          localTerm.write('\r\x1b[K$ ' + prevCommand); // Escaped sequence
                          lineBuffer = prevCommand;
                     }
                  } else if (sequence === '[B') { // Down
                      if (historyIndex.current < commandHistory.current.length - 1) {
                          historyIndex.current++;
                          const nextCommand = commandHistory.current[historyIndex.current];
                          localTerm.write('\r\x1b[K$ ' + nextCommand); // Escaped sequence
                          lineBuffer = nextCommand;
                      } else if (historyIndex.current === commandHistory.current.length - 1) {
                          historyIndex.current++;
                          localTerm.write('\r\x1b[K$ '); // Escaped sequence
                          lineBuffer = "";
                      }
                  }
              } else if (code >= 32 && code <= 126) { // Printable
                  lineBuffer += data;
                  localTerm.write(data);
              } else {
                  console.log("Ignoring non-printable character, code:", code);
              }
          });

          // --- Resize handling ---
          resizeObserver = new ResizeObserver(() => {
              try {
                 fitAddon.current?.fit();
              } catch (e) {
                 console.error("Error fitting terminal:", e);
              }
          });
          if (terminalRef.current) {
              resizeObserver.observe(terminalRef.current);
              resizeObserverRef.current = resizeObserver; // Store observer in ref
          }

          localTerm.writeln('Terminal initialized. Connect to a sandbox.');

          // --- Connect if sandboxId is already available ---
          if (sandboxId) {
              connectWebSocket();
          }

      }).catch(err => {
          console.error("Failed to load xterm modules:", err);
          onLog("ERROR: Failed to load terminal library.");
      });

      // --- Cleanup function for this effect ---
      return () => {
          console.log("Cleaning up TerminalComponent effect");
          // Disconnect observer using the ref
          if (resizeObserverRef.current && terminalRef.current) {
              resizeObserverRef.current.unobserve(terminalRef.current);
          }
          resizeObserverRef.current = null;

          // Dispose terminal
          if (term.current) {
              term.current.dispose();
              term.current = null;
          }
          fitAddon.current = null;
          cleanupWebSocket(); // Ensure WebSocket is closed on unmount
      };
    }
    // Intentionally omitting connectWebSocket and prompt from deps here
    // as they are stable due to useCallback and we only want init logic
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isClient, sandboxId, onCommand, onLog, cleanupWebSocket]);

  // --- Effect for WebSocket connection based on sandboxId ---
  useEffect(() => {
    // Only connect/disconnect if terminal is initialized and client-side
    if (isClient && term.current) {
        if (sandboxId) {
            connectWebSocket();
        } else {
            cleanupWebSocket();
            // Correctly escaped ANSI codes
            term.current.writeln('\r\n\x1b[1;33mINFO: Disconnected. Please enter a Sandbox ID and connect.\x1b[0m');
        }
    }

    // Cleanup WebSocket on sandboxId change or unmount
    // This return is important if connectWebSocket was called
    return () => {
        if (sandboxId) { // Only cleanup if we might have connected
            cleanupWebSocket();
        }
    };
  }, [sandboxId, isClient, term.current, connectWebSocket, cleanupWebSocket]); // Added term.current as dependency


  // --- Conditional Rendering ---
  if (!isClient) {
      return <div className="w-full h-full flex items-center justify-center bg-gray-200 dark:bg-gray-800"><p>Initializing Terminal...</p></div>;
  }

  return <div id="terminal" ref={terminalRef} className="w-full h-full bg-black text-white p-2"></div>;
};

export default TerminalComponent;