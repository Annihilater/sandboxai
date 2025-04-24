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