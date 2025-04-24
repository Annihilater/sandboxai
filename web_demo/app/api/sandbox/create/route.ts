import { NextResponse } from 'next/server';

const RUNTIME_URL = process.env.RUNTIME_URL || 'http://localhost:5266';

export async function POST() {
  try {
    const response = await fetch(`${RUNTIME_URL}/v1/spaces/default/sandboxes`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });

    if (!response.ok) {
      throw new Error(`Failed to create sandbox: ${response.statusText}`);
    }

    const data = await response.json();
    
    return NextResponse.json({
      id: data.sandbox_id,
      agentUrl: data.agent_url,
      isRunning: data.is_running,
    });
  } catch (error) {
    console.error('Error creating sandbox:', error);
    return NextResponse.json(
      { error: 'Failed to create sandbox' },
      { status: 500 }
    );
  }
} 