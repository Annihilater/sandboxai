import { NextResponse } from 'next/server';

const RUNTIME_URL = process.env.RUNTIME_URL || 'http://localhost:5266';

export async function GET() {
  try {
    const response = await fetch(`${RUNTIME_URL}/v1/spaces/default`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch sandboxes: ${response.statusText}`);
    }

    const data = await response.json();
    
    // 提取沙箱列表并格式化
    const sandboxes = Object.entries(data.Sandboxes || {}).map(([id, state]: [string, any]) => ({
      id,
      isRunning: state.is_running,
      agentUrl: state.agent_url,
      containerId: state.container_id,
    }));

    return NextResponse.json({ sandboxes });
  } catch (error) {
    console.error('Error fetching sandboxes:', error);
    return NextResponse.json(
      { error: 'Failed to fetch sandboxes' },
      { status: 500 }
    );
  }
} 