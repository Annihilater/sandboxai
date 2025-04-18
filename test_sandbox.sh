#!/bin/bash

# Script to run a comprehensive test suite against a MentisSandbox instance.

# --- Configuration ---
BASE_URL="http://127.0.0.1:5266"
# Prompt for the Sandbox ID
read -p "Enter the Sandbox ID to test: " SANDBOX_ID

# Validate Sandbox ID
if [ -z "$SANDBOX_ID" ]; then
  echo "Error: Sandbox ID cannot be empty."
  exit 1
fi

echo "--- Starting Test Suite for Sandbox ID: $SANDBOX_ID ---"
echo "--- Base URL: $BASE_URL ---"
echo "--- Remember to monitor the WebSocket stream in another terminal: ---"
echo "--- websocat ws://127.0.0.1:5266/sandboxes/$SANDBOX_ID/stream ---"
echo ""
sleep 3 # Give user time to read

# --- Helper Function ---
# Usage: run_test <test_number> <description> <endpoint> <json_payload>
run_test() {
  local test_num=$1
  local description=$2
  local endpoint=$3
  local payload=$4
  local url="${BASE_URL}/sandboxes/${SANDBOX_ID}/${endpoint}"

  echo "--- Test $test_num: $description ---"
  echo "Endpoint: $url"
  echo "Payload: $payload"

  # Execute curl command
  curl -X POST "$url" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --silent --output /dev/null # Suppress curl output unless debugging

  # Check curl exit status (optional, basic check)
  if [ $? -ne 0 ]; then
    echo "Warning: curl command for Test $test_num might have failed."
  fi

  echo "" # Newline for readability
  sleep 1 # Short pause between tests
}

# --- Test Cases ---

# === Basic Execution ===
run_test 1 "Basic Shell Command" "shell" '{"command": "echo \"Test 1: Basic Shell OK\""}'
run_test 2 "Basic IPython Execution" "ipython" '{"code": "print(\"Test 2: Basic IPython OK\")", "split_output": true}'
run_test 3 "Shell Command with Args" "shell" '{"command": "ls -l /work"}'
run_test 4 "IPython Multi-line Code" "ipython" '{"code": "import sys\nprint(f\"Test 4: Python Version: {sys.version_info.major}.{sys.version_info.minor}\")", "split_output": true}'

# === State Persistence (IPython) ===
run_test 5 "IPython State - Set Variable" "ipython" '{"code": "test_var_5 = 123\nprint(f\"Test 5: Set test_var_5 = {test_var_5}\")", "split_output": true}'
run_test 6 "IPython State - Get Variable" "ipython" '{"code": "try:\n    print(f\"Test 6: Get test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 6: Variable test_var_5 not found!\")", "split_output": true}'
run_test 7 "IPython State - Modify Variable" "ipython" '{"code": "try:\n    test_var_5 += 1\n    print(f\"Test 7: Modified test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 7: Variable test_var_5 not found!\")", "split_output": true}'
run_test 8 "IPython State - Check Modified Variable" "ipython" '{"code": "try:\n    print(f\"Test 8: Check modified test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 8: Variable test_var_5 not found!\")", "split_output": true}'

# === Libraries and Computation ===
run_test 9 "IPython NumPy Basic" "ipython" '{"code": "import numpy as np\na = np.array([1, 2, 3])\nprint(f\"Test 9: NumPy array: {a}\")", "split_output": true}'
run_test 10 "IPython NumPy Calculation" "ipython" '{"code": "import numpy as np\narr = np.arange(6).reshape((2, 3))\nprint(f\"Test 10: NumPy sum: {np.sum(arr)}\")", "split_output": true}'
run_test 11 "IPython Standard Library (datetime)" "ipython" '{"code": "import datetime\nprint(f\"Test 11: Current time (UTC): {datetime.datetime.utcnow()}\")", "split_output": true}'
run_test 12 "IPython Standard Library (json)" "ipython" '{"code": "import json\ndata = {\"key\": \"value\", \"num\": 1}\nprint(f\"Test 12: JSON dump: {json.dumps(data)}\")", "split_output": true}'

# === File System Operations ===
run_test 13 "Shell Create File" "shell" '{"command": "echo \"Test 13 Content\" > /work/test13.txt && echo \"Test 13: File created\""}'
run_test 14 "Shell Read File" "shell" '{"command": "cat /work/test13.txt"}'
run_test 15 "IPython Read File" "ipython" '{"code": "try:\n    with open(\"/work/test13.txt\", \"r\") as f:\n        content = f.read().strip()\n        print(f\"Test 15: Read from IPython: {content}\")\nexcept FileNotFoundError:\n    print(\"Test 15: File not found!\")", "split_output": true}'
run_test 16 "Shell Append to File" "shell" '{"command": "echo \"Appended Content\" >> /work/test13.txt && echo \"Test 16: Appended to file\""}'
run_test 17 "IPython Read Appended File" "ipython" '{"code": "try:\n    with open(\"/work/test13.txt\", \"r\") as f:\n        content = f.read()\n        print(f\"Test 17: Read appended content:\\n{content}\")\nexcept FileNotFoundError:\n    print(\"Test 17: File not found!\")", "split_output": true}'
run_test 18 "Shell List Directory" "shell" '{"command": "ls -la /work"}'

# === Environment Variables ===
run_test 19 "Shell Set ENV VAR (Export might not persist)" "shell" '{"command": "export TEST_VAR_19=\"ShellValue\" && echo \"Test 19: Set TEST_VAR_19 (may not persist)\""}'
run_test 20 "IPython Read ENV VAR (Shell Export)" "ipython" '{"code": "import os\nval = os.environ.get(\"TEST_VAR_19\", \"Not Set\")\nprint(f\"Test 20: IPython reads TEST_VAR_19: {val}\")", "split_output": true}' # Likely "Not Set"
run_test 21 "IPython Set ENV VAR" "ipython" '{"code": "import os\nos.environ[\"TEST_VAR_21\"] = \"IPythonValue\"\nprint(f\"Test 21: IPython set TEST_VAR_21\")", "split_output": true}'
run_test 22 "IPython Read ENV VAR (IPython Set)" "ipython" '{"code": "import os\nval = os.environ.get(\"TEST_VAR_21\", \"Not Set\")\nprint(f\"Test 22: IPython reads TEST_VAR_21: {val}\")", "split_output": true}' # Should be "IPythonValue"

# === Error Handling ===
run_test 23 "Shell Non-existent Command" "shell" '{"command": "this_command_does_not_exist_xyz"}'
run_test 24 "Shell Command Non-Zero Exit" "shell" '{"command": "ls /nonexistent_directory_abc"}'
run_test 25 "IPython NameError" "ipython" '{"code": "print(undefined_variable_for_test_25)", "split_output": true}'
run_test 26 "IPython SyntaxError" "ipython" '{"code": "print(\"Test 26: Syntax Error\" oops)", "split_output": true}'
run_test 27 "IPython ZeroDivisionError" "ipython" '{"code": "result = 1 / 0\nprint(result)", "split_output": true}'

# === Large Output ===
run_test 28 "Shell Large Output (Reduced)" "shell" '{"command": "seq 1 20 | while read i; do echo \"Shell Line $i\"; done"}' # Reduced from 100 for brevity
run_test 29 "IPython Large Output (Reduced)" "ipython" '{"code": "for i in range(1, 21):\n    print(f\"IPython Line {i}\")", "split_output": true}' # Reduced from 100

# === System Info / Verification ===
run_test 30 "Shell System Info" "shell" '{"command": "echo \"--- Sys Info ---\" && uname -a && echo \"--- Python Info ---\" && python3 --version && echo \"--- IPython Info ---\" && ipython --version && echo \"--- Working Dir ---\" && pwd && echo \"--- User ---\" && whoami"}'

# === Bonus: Verify Agent Code (Adjust path if needed) ===
# run_test 31 "Verify Agent Code Snippet" "shell" '{"command": "grep -A 3 \"Sending IPython result observation\" /sandboxai/mentis_executor/main.py || echo \"Code snippet not found\""}'


echo "--- Test Suite Completed for Sandbox ID: $SANDBOX_ID ---"