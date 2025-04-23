#!/bin/bash
# --- Configuration ---
BASE_URL="http://127.0.0.1:5266" # 确保这是你 Runtime 服务的地址和端口

# --- Prompt for the Sandbox ID ---
# 让用户输入要测试的、已经存在的 Sandbox ID
read -p "请输入要测试的 Sandbox ID: " SANDBOX_ID

# --- Validate Sandbox ID ---
# 检查用户是否输入了 ID
if [ -z "$SANDBOX_ID" ]; then
  echo "错误: Sandbox ID 不能为空。"
  exit 1
fi

# --- Initial Output ---
echo "--- 开始为 Sandbox ID 进行测试: $SANDBOX_ID ---"
echo "--- API 基础 URL: $BASE_URL ---"
echo "--- 请确保在另一个终端监控 WebSocket 输出: ---"
# 构造正确的 WebSocket URL (假设在 default space)
echo "--- websocat ws://127.0.0.1:5266/v1/sandboxes/$SANDBOX_ID/stream ---"
echo ""
sleep 3 # 给用户一点时间阅读提示信息

# --- Helper Function ---
# Usage: run_test <test_number> <description> <endpoint_suffix> <json_payload>
run_test() {
  local test_num=$1
  local description=$2
  local endpoint_suffix=$3 # Endpoint suffix like 'shell' or 'ipython'
  local payload=$4
  # --- 修正 URL 构造 ---
  # 假设所有测试都在 'default' space 下进行
  local space_id="default"
  local url="${BASE_URL}/v1/spaces/${space_id}/sandboxes/${SANDBOX_ID}/${endpoint_suffix}"
  # --- 修正结束 ---

  echo "--- 测试 $test_num: $description ---"
  echo "请求 URL: $url"
  echo "请求体 (Payload): $payload"
  echo "发送请求..."

  # Execute curl command
  # 添加 -w "%{http_code}" 来打印 HTTP 状态码，方便快速检查 API 是否通畅
  http_status=$(curl -X POST "$url" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --silent --output /dev/null \
    -w "%{http_code}")

  # 检查 curl 退出状态和 HTTP 状态码
  if [ $? -ne 0 ]; then
    echo "警告: 测试 $test_num 的 curl 命令本身执行失败。"
  elif [[ "$http_status" -ne 200 && "$http_status" -ne 202 ]]; then # 接受 200 或 202
    echo "警告: 测试 $test_num 的 API 请求返回了非成功状态码: HTTP $http_status"
  else
    echo "API 请求成功 (HTTP $http_status)。请检查 WebSocket 输出确认执行结果。"
  fi

  echo "" # Newline for readability
  sleep 1 # 在测试之间短暂停顿
}

# --- Test Cases ---
# (测试用例保持不变，因为它们的目的是触发不同的命令)

# === Basic Execution ===
run_test 1 "基础 Shell 命令" "tools:run_shell_command" '{"command": "echo \"Test 1: Basic Shell OK\""}'
run_test 2 "基础 IPython 执行" "tools:run_ipython_cell" '{"code": "print(\"Test 2: Basic IPython OK\")"}' # 移除了 split_output
run_test 3 "带参数的 Shell 命令" "tools:run_shell_command" '{"command": "ls -l /work"}' # 假设工作目录是 /work
run_test 4 "多行 IPython 代码" "tools:run_ipython_cell" '{"code": "import sys\nprint(f\"Test 4: Python Version: {sys.version_info.major}.{sys.version_info.minor}\")"}'

# === State Persistence (IPython) ===
run_test 5 "IPython 状态 - 设置变量" "tools:run_ipython_cell" '{"code": "test_var_5 = 123\nprint(f\"Test 5: Set test_var_5 = {test_var_5}\")"}'
run_test 6 "IPython 状态 - 获取变量" "tools:run_ipython_cell" '{"code": "try:\n    print(f\"Test 6: Get test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 6: Variable test_var_5 not found!\")"}'
run_test 7 "IPython 状态 - 修改变量" "tools:run_ipython_cell" '{"code": "try:\n    test_var_5 += 1\n    print(f\"Test 7: Modified test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 7: Variable test_var_5 not found!\")"}'
run_test 8 "IPython 状态 - 检查修改后变量" "tools:run_ipython_cell" '{"code": "try:\n    print(f\"Test 8: Check modified test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 8: Variable test_var_5 not found!\")"}'

# === Libraries and Computation ===
run_test 9 "IPython NumPy 基础" "tools:run_ipython_cell" '{"code": "import numpy as np\na = np.array([1, 2, 3])\nprint(f\"Test 9: NumPy array: {a}\")"}'
run_test 10 "IPython NumPy 计算" "tools:run_ipython_cell" '{"code": "import numpy as np\narr = np.arange(6).reshape((2, 3))\nprint(f\"Test 10: NumPy sum: {np.sum(arr)}\")"}'
run_test 11 "IPython 标准库 (datetime)" "tools:run_ipython_cell" '{"code": "import datetime\nprint(f\"Test 11: Current time (UTC): {datetime.datetime.utcnow()}\")"}'
run_test 12 "IPython 标准库 (json)" "tools:run_ipython_cell" '{"code": "import json\ndata = {\"key\": \"value\", \"num\": 1}\nprint(f\"Test 12: JSON dump: {json.dumps(data)}\")"}'

# === File System Operations ===
run_test 13 "Shell 创建文件" "tools:run_shell_command" '{"command": "echo \"Test 13 Content\" > /work/test13.txt && echo \"Test 13: File created\""}'
run_test 14 "Shell 读取文件" "tools:run_shell_command" '{"command": "cat /work/test13.txt"}'
run_test 15 "IPython 读取文件" "tools:run_ipython_cell" '{"code": "try:\n    with open(\"/work/test13.txt\", \"r\") as f:\n        content = f.read().strip()\n        print(f\"Test 15: Read from IPython: {content}\")\nexcept FileNotFoundError:\n    print(\"Test 15: File not found!\")"}'
run_test 16 "Shell 追加文件" "tools:run_shell_command" '{"command": "echo \"Appended Content\" >> /work/test13.txt && echo \"Test 16: Appended to file\""}'
run_test 17 "IPython 读取追加后文件" "tools:run_ipython_cell" '{"code": "try:\n    with open(\"/work/test13.txt\", \"r\") as f:\n        content = f.read()\n        print(f\"Test 17: Read appended content:\\n{content}\")\nexcept FileNotFoundError:\n    print(\"Test 17: File not found!\")"}'
run_test 18 "Shell 列出目录" "tools:run_shell_command" '{"command": "ls -la /work"}'

# === Environment Variables ===
run_test 19 "Shell 设置环境变量 (Export 可能不持久)" "tools:run_shell_command" '{"command": "export TEST_VAR_19=\"ShellValue\" && echo \"Test 19: Set TEST_VAR_19 (may not persist)\""}'
run_test 20 "IPython 读取环境变量 (来自Shell Export)" "tools:run_ipython_cell" '{"code": "import os\nval = os.environ.get(\"TEST_VAR_19\", \"Not Set\")\nprint(f\"Test 20: IPython reads TEST_VAR_19: {val}\")"}' # 预期是 "Not Set"
run_test 21 "IPython 设置环境变量" "tools:run_ipython_cell" '{"code": "import os\nos.environ[\"TEST_VAR_21\"] = \"IPythonValue\"\nprint(f\"Test 21: IPython set TEST_VAR_21\")"}'
run_test 22 "IPython 读取环境变量 (来自IPython Set)" "tools:run_ipython_cell" '{"code": "import os\nval = os.environ.get(\"TEST_VAR_21\", \"Not Set\")\nprint(f\"Test 22: IPython reads TEST_VAR_21: {val}\")"}' # 预期是 "IPythonValue"

# === Error Handling ===
run_test 23 "Shell 不存在的命令" "tools:run_shell_command" '{"command": "this_command_does_not_exist_xyz"}'
run_test 24 "Shell 命令非零退出" "tools:run_shell_command" '{"command": "ls /nonexistent_directory_abc"}'
run_test 25 "IPython NameError" "tools:run_ipython_cell" '{"code": "print(undefined_variable_for_test_25)"}'
run_test 26 "IPython SyntaxError" "tools:run_ipython_cell" '{"code": "print(\"Test 26: Syntax Error\" oops)"}'
run_test 27 "IPython ZeroDivisionError" "tools:run_ipython_cell" '{"code": "result = 1 / 0\nprint(result)"}'

# === Large Output ===
run_test 28 "Shell 大量输出 (已减少)" "tools:run_shell_command" '{"command": "seq 1 20 | while read i; do echo \"Shell Line $i\"; done"}'
run_test 29 "IPython 大量输出 (已减少)" "tools:run_ipython_cell" '{"code": "for i in range(1, 21):\n    print(f\"IPython Line {i}\")"}'

# === System Info / Verification ===
run_test 30 "Shell 系统信息" "tools:run_shell_command" '{"command": "echo \"--- Sys Info ---\" && uname -a && echo \"--- Python Info ---\" && python3 --version && echo \"--- IPython Info ---\" && ipython --version && echo \"--- Working Dir ---\" && pwd && echo \"--- User ---\" && whoami"}'

# === Bonus: Verify Agent Code (Adjust path if needed) ===
# run_test 31 "Verify Agent Code Snippet" "shell" '{"command": "grep -A 3 \"Send result observation\" /sandbox/mentis_executor/main.py || echo \"Code snippet not found\""}' # Adjusted path to /sandbox


echo "--- 测试套件执行完毕 Sandbox ID: $SANDBOX_ID ---"