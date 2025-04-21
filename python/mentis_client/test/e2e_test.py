# mentis_client/test/e2e_test.py
import os
import pytest
import json
import time
from queue import Queue
from typing import Dict, Any, List, Optional

from mentis_client import MentisSandbox
from mentis_client.spaces import SpaceManager
from mentis_client.api import (
    CreateSpaceRequest,
    UpdateSpaceRequest,
    CreateSandboxRequest,
    SandboxSpec
)
from mentis_client.error import (
    MentisError,
    MentisAPIError,
    MentisValidationError,
    MentisConnectionError,
    MentisTimeoutError
)

# 从环境变量获取测试配置
BASE_URL = os.environ.get("MENTIS_RUNTIME_URL", "http://localhost:5266")

@pytest.fixture(scope="session")
def space_manager():
    """创建SpaceManager实例用于测试"""
    return SpaceManager(base_url=BASE_URL)

@pytest.fixture(scope="function")
def sandbox_session(space_manager):
    """创建一个MentisSandbox实例，连接流，并在测试后自动删除"""
    obs_queue = Queue()  # 用于在测试主线程和回调之间安全传输数据的队列
    
    try:
        # 首先创建一个空间
        space_name = f"test-space-{int(time.time())}"
        space_request = CreateSpaceRequest(
            name=space_name,
            description="测试空间"
        )
        space = space_manager.create_space(space_request)
        
        print(f"\n[测试设置] 通过 {BASE_URL} 创建沙箱...")
        box = MentisSandbox.create(
            base_url=BASE_URL,
            observation_queue=obs_queue,
            settings={"space_id": space.space_id}
        )
        print(f"[测试设置] 沙箱已创建: {box.sandbox_id}")
        
        print("[测试设置] 连接到流...")
        box.connect_stream(timeout=10.0)  # 等待连接
        assert box.is_stream_connected(), "无法连接到WebSocket流"
        print("[测试设置] 流已连接.")
        
        yield box, obs_queue  # 向测试函数提供沙箱实例和队列
        
    except Exception as e:
        pytest.fail(f"沙箱创建或连接在设置期间失败: {e}")
    finally:
        if 'box' in locals():
            print(f"\n[测试清理] 删除沙箱 {box.sandbox_id}...")
            try:
                box.delete()
            except Exception as e:
                print(f"清理过程中删除沙箱时出错: {e}")
        if 'space' in locals():
            print(f"\n[测试清理] 删除空间 {space.name}...")
            try:
                space_manager.delete_space(space.space_id)
            except Exception as e:
                print(f"清理过程中删除空间时出错: {e}")

def test_run_code(sandbox_session):
    """测试代码执行功能"""
    sandbox, obs_queue = sandbox_session
    
    # 执行简单的Python代码
    code = "print('Hello, World!')"
    action_id = sandbox.run_ipython_cell(code)
    
    print(f"\n[调试] 执行代码，action_id: {action_id}")
    
    # 收集观察结果
    observations = collect_observations(obs_queue, action_id, timeout=10)
    
    # 打印所有观察结果以便调试
    print("\n[调试] 收到的观察结果:")
    for obs in observations:
        print(f"- 类型: {obs.observation_type}")
        if hasattr(obs, 'stream'):
            print(f"  流: {obs.stream}")
        if hasattr(obs, 'line'):
            print(f"  行: {obs.line}")
        if hasattr(obs, 'data'):
            print(f"  数据: {obs.data}")
    
    # 验证结果
    output_obs = [obs for obs in observations
                 if hasattr(obs, 'stream') and obs.stream == "stdout"]
    assert len(output_obs) > 0, "未收到任何标准输出观察结果"
    
    # 验证输出内容
    output = "".join([obs.line for obs in output_obs if hasattr(obs, 'line')])
    assert "Hello, World!" in output, f"输出内容不匹配: {output}"

def test_run_shell_command(sandbox_session):
    """测试Shell命令执行功能"""
    sandbox, obs_queue = sandbox_session
    
    # 执行简单的Shell命令
    command = "echo 'Hello from shell'"
    action_id = sandbox.run_shell_command(command)
    
    # 收集观察结果
    observations = collect_observations(obs_queue, action_id, timeout=10)
    
    # 验证结果
    output_obs = [obs for obs in observations 
                 if hasattr(obs, 'stream') and obs.stream == "stdout"]
    assert any("Hello from shell" in str(obs.line) for obs in output_obs), "未找到预期的输出"
    
    # 验证执行完成
    end_obs = [obs for obs in observations if obs.observation_type == "result"]
    assert len(end_obs) > 0, "未收到执行结束的观察结果"
    assert end_obs[0].exit_code == 0, f"命令执行失败: {end_obs[0]}"

def test_space_management(space_manager):
    """测试空间管理功能"""
    # 创建测试空间
    space_name = f"test-space-{int(time.time())}"
    space_request = CreateSpaceRequest(
        name=space_name,
        description="测试空间"
    )
    space = space_manager.create_space(space_request)
    
    try:
        # 验证空间创建成功
        assert space.name == space_name, "空间名称不匹配"
        
        # 获取空间
        retrieved_space = space_manager.get_space(space.space_id)
        assert retrieved_space.name == space_name, "获取的空间名称不匹配"
        
        # 列出所有空间
        spaces = space_manager.list_spaces()
        assert any(s.name == space_name for s in spaces), "在空间列表中未找到创建的空间"
        
        # 更新空间
        update_request = UpdateSpaceRequest(description="更新的测试空间")
        updated_space = space_manager.update_space(space.space_id, update_request)
        assert updated_space.description == "更新的测试空间", "空间描述未更新"
        
        # 在空间中创建沙箱
        sandbox_request = CreateSandboxRequest(
            name="test-sandbox",
            spec=SandboxSpec(image="python:3.9")
        )
        sandbox = space_manager.create_sandbox(space.space_id, sandbox_request)
        
        # 验证沙箱创建成功
        assert sandbox.name == "test-sandbox", "沙箱名称不匹配"
        
        # 获取沙箱
        retrieved_sandbox = space_manager.get_sandbox(space.space_id, "test-sandbox")
        assert retrieved_sandbox.name == "test-sandbox", "获取的沙箱名称不匹配"
        
        # 列出空间中的所有沙箱
        sandboxes = space_manager.list_sandboxes(space.space_id)
        assert any(s.name == "test-sandbox" for s in sandboxes), "在沙箱列表中未找到创建的沙箱"
        
        # 删除沙箱
        space_manager.delete_sandbox(space.space_id, "test-sandbox")
        
        # 验证沙箱已删除
        with pytest.raises(MentisAPIError) as exc_info:
            space_manager.get_sandbox(space.space_id, "test-sandbox")
        assert exc_info.value.status_code == 404, "沙箱删除失败"
    
    finally:
        # 清理：删除测试空间
        space_manager.delete_space(space.space_id)

def test_error_handling(space_manager):
    """测试错误处理功能"""
    # 测试无效空间ID
    with pytest.raises(MentisAPIError) as exc_info:
        space_manager.get_space("non-existent-space")
    assert "space not found" in str(exc_info.value)
    assert exc_info.value.status_code == 404
    
    # 测试无效沙箱ID
    space_name = f"test-space-{int(time.time())}"
    space_request = CreateSpaceRequest(name=space_name)
    space = space_manager.create_space(space_request)
    
    try:
        with pytest.raises(MentisAPIError) as exc_info:
            space_manager.get_sandbox(space_name, "non-existent-sandbox")
        assert exc_info.value.status_code == 404, "无效沙箱ID未返回404错误"
        
        # 测试无效镜像标签
        with pytest.raises(MentisValidationError) as exc_info:
            sandbox_request = CreateSandboxRequest(
                name="invalid-sandbox",
                spec=SandboxSpec(image="python")  # 缺少标签
            )
            space_manager.create_sandbox(space_name, sandbox_request)
        assert "Image must include a tag" in str(exc_info.value), "无效镜像标签未返回正确错误"
        
        # 测试重复空间名
        with pytest.raises(MentisAPIError) as exc_info:
            space_manager.create_space(space_request)
        assert exc_info.value.status_code == 409, "重复空间名未返回409错误"
        
        # 测试无效请求格式
        with pytest.raises(MentisValidationError) as exc_info:
            invalid_request = {"invalid_field": "value"}
            space_manager.create_space(invalid_request)
        assert "validation error" in str(exc_info.value).lower(), "无效请求格式未返回正确错误"
    
    finally:
        # 清理：删除测试空间
        space_manager.delete_space(space_name)

def collect_observations(queue: Queue, action_id: str, timeout: float = 10.0) -> List[Any]:
    """从队列中收集与特定action_id相关的所有观察结果"""
    observations = []
    end_time = time.time() + timeout
    end_received = False
    
    print(f"\n[调试] 开始收集观察结果，action_id: {action_id}")
    
    while time.time() < end_time and not end_received:
        try:
            obs = queue.get(timeout=0.5)
            print(f"\n[调试] 收到观察结果:")
            print(f"- 类型: {obs.observation_type}")
            print(f"- action_id: {obs.action_id}")
            if hasattr(obs, 'stream'):
                print(f"- 流: {obs.stream}")
            if hasattr(obs, 'line'):
                print(f"- 行: {obs.line}")
            if hasattr(obs, 'data'):
                print(f"- 数据: {obs.data}")
            
            # 只收集与我们的action_id匹配的观察结果
            if obs.action_id == action_id:
                observations.append(obs)
                print(f"[调试] 添加到观察结果列表")
                
                # 检查是否收到了结束观察结果
                if obs.observation_type in ("result", "end"):
                    end_received = True
                    print(f"[调试] 收到结束观察结果")
            else:
                print(f"[调试] action_id 不匹配，跳过")
            
            queue.task_done()
        except Exception as e:
            # 队列可能为空，继续等待
            print(f"[调试] 等待观察结果时出错: {str(e)}")
            pass
    
    print(f"\n[调试] 观察结果收集完成:")
    print(f"- 总观察结果数: {len(observations)}")
    print(f"- 是否收到结束信号: {end_received}")
    
    return observations