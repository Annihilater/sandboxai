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