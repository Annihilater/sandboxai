// Filepath: components/DebugView.tsx
import React from 'react';

interface DebugViewProps {
  logs: string[];
}

const DebugView: React.FC<DebugViewProps> = ({ logs }) => {
  return (
    <div className="h-full overflow-auto bg-slate-900 text-slate-200 font-mono text-sm p-4">
      {logs.map((log, index) => (
        <div 
          key={index} 
          className="py-1 border-b border-slate-800 last:border-0"
        >
          {log}
        </div>
      ))}
    </div>
  );
};

export default DebugView;