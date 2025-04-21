#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from mentis_client import MentisSandbox, MentisError, MentisAPIError, MentisValidationError, MentisTimeoutError
from mentis_client.client import collect_observations

# 获取测试用例目录
TEST_CASES_DIR = Path(__file__).parent / "cases"

def load_test_cases(filename: str) -> List[Dict[str, Any]]:
    """加载测试用例文件
    
    Args:
        filename: 测试用例文件名
        
    Returns:
        测试用例列表
    """
    with open(TEST_CASES_DIR / filename) as f:
        return json.load(f)

def run_ipython_cell_test(sandbox: MentisSandbox, test_case: Dict[str, Any]) -> None:
    """运行 IPython cell 测试用例
    
    Args:
        sandbox: MentisSandbox 实例
        test_case: 测试用例
    """
    result = sandbox.run_code(test_case["code"], split=test_case.get("split", False))
    
    if "expected_output" in test_case:
        assert result.output == test_case["expected_output"]
    if "expected_output_contains" in test_case:
        assert test_case["expected_output_contains"] in result.output
    if "expected_stdout" in test_case:
        assert result.stdout == test_case["expected_stdout"]
    if "expected_stderr" in test_case:
        assert result.stderr == test_case["expected_stderr"]

def run_shell_command_test(sandbox: MentisSandbox, test_case: Dict[str, Any]) -> None:
    """运行 shell 命令测试用例
    
    Args:
        sandbox: MentisSandbox 实例
        test_case: 测试用例
    """
    result = sandbox.run_shell_command(
        test_case["command"],
        split=test_case.get("split", False)
    )
    
    if "expected_output" in test_case:
        assert result.output == test_case["expected_output"]
    if "expected_stdout" in test_case:
        assert result.stdout == test_case["expected_stdout"]
    if "expected_stderr" in test_case:
        assert result.stderr == test_case["expected_stderr"]

def run_space_management_test(space_manager: Any, test_case: Dict[str, Any]) -> None:
    """运行空间管理测试用例
    
    Args:
        space_manager: SpaceManager 实例
        test_case: 测试用例
    """
    operation = test_case["operation"]
    
    if operation == "create_space":
        result = space_manager.create_space(test_case["request"])
        assert result.name == test_case["expected"]["name"]
        assert result.description == test_case["expected"]["description"]
        
    elif operation == "get_space":
        result = space_manager.get_space(test_case["space_id"])
        assert result.name == test_case["expected"]["name"]
        assert result.description == test_case["expected"]["description"]
        
    elif operation == "update_space":
        result = space_manager.update_space(test_case["space_id"], test_case["request"])
        assert result.name == test_case["expected"]["name"]
        assert result.description == test_case["expected"]["description"]
        
    elif operation == "create_sandbox":
        result = space_manager.create_sandbox(test_case["space_id"], test_case["request"])
        assert result.name == test_case["expected"]["name"]
        assert result.spec.image == test_case["expected"]["spec"]["image"]
        
    elif operation == "get_sandbox":
        result = space_manager.get_sandbox(test_case["space_id"], test_case["sandbox_id"])
        assert result.name == test_case["expected"]["name"]
        assert result.spec.image == test_case["expected"]["spec"]["image"]
        
    elif operation == "delete_sandbox":
        space_manager.delete_sandbox(test_case["space_id"], test_case["sandbox_id"])
        
    elif operation == "delete_space":
        space_manager.delete_space(test_case["space_id"])

def run_error_handling_test(space_manager: Any, test_case: Dict[str, Any]) -> None:
    """运行错误处理测试用例
    
    Args:
        space_manager: SpaceManager 实例
        test_case: 测试用例
    """
    operation = test_case["operation"]
    expected_error = test_case["expected_error"]
    
    with pytest.raises(eval(expected_error["type"])) as exc_info:
        if operation == "create_space":
            space_manager.create_space(test_case["request"])
        elif operation == "get_space":
            space_manager.get_space(test_case["space_id"])
        elif operation == "create_sandbox":
            space_manager.create_sandbox(test_case["space_id"], test_case["request"])
        elif operation == "get_sandbox":
            space_manager.get_sandbox(test_case["space_id"], test_case["sandbox_id"])
    
    error = exc_info.value
    if "status_code" in expected_error:
        assert error.status_code == expected_error["status_code"]
    if "message_contains" in expected_error:
        assert expected_error["message_contains"] in str(error)

@pytest.fixture(scope="session")
def base_url() -> str:
    """获取基础 URL"""
    return os.environ.get("MENTIS_RUNTIME_URL", "http://localhost:5266")

@pytest.fixture(scope="session")
def space_manager(base_url: str):
    """创建 SpaceManager 实例"""
    from mentis_client import SpaceManager
    return SpaceManager(base_url)

@pytest.fixture(scope="function")
def sandbox(base_url: str):
    """创建 MentisSandbox 实例"""
    with MentisSandbox.create(base_url=base_url) as s:
        yield s

def test_ipython_cell(sandbox: MentisSandbox):
    """测试 IPython cell 执行"""
    test_cases = load_test_cases("run_ipython_cell.json")
    for test_case in test_cases:
        run_ipython_cell_test(sandbox, test_case)

def test_shell_command(sandbox: MentisSandbox):
    """测试 shell 命令执行"""
    test_cases = load_test_cases("run_shell_command.json")
    for test_case in test_cases:
        run_shell_command_test(sandbox, test_case)

def test_space_management(space_manager: Any):
    """测试空间管理功能"""
    test_cases = load_test_cases("space_management.json")
    for test_case in test_cases:
        run_space_management_test(space_manager, test_case)

def test_error_handling(space_manager: Any):
    """测试错误处理"""
    test_cases = load_test_cases("error_handling.json")
    for test_case in test_cases:
        run_error_handling_test(space_manager, test_case)

def test_run_code():
    """Test running Python code in the sandbox."""
    sandbox = MentisSandbox()
    try:
        code = "print('Hello, World!')"
        action_id = sandbox.run_ipython_cell(code)
        observations = collect_observations(sandbox.obs_queue, action_id)
        output = "".join([obs.line for obs in observations if hasattr(obs, 'line')])
        assert "Hello, World!" in output
    finally:
        sandbox.close()

if __name__ == "__main__":
    pytest.main([__file__] + sys.argv[1:]) 