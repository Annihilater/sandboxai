#!/bin/bash
# ============================================
# Mentis Sandbox - Manual API Test Script
# ============================================
# Purpose: Sends various commands (Shell and IPython) to a specified sandbox
#          via the MentisRuntime API for manual verification.
#
# Verification: REQUIRES MANUAL verification. You need to monitor the
#               WebSocket stream output in a separate terminal using 'websocat'
#               to see the actual results and outputs of the commands.
#
# Usage:
# 1. Make sure your Docker daemon is running.
# 2. Make sure the MentisRuntime Go service is running.
#    (If not, navigate to the project root and run: go run ./go/mentisruntime/main.go)
# 3. Run this script: ./manual_api_tests.sh
# 4. Follow the instructions to create a sandbox and get its ID.
# 5. Open *another* terminal window and run the 'websocat' command provided.
# 6. Switch back to this script and press Enter when prompted.
# ============================================

# --- Configuration ---
BASE_URL="http://127.0.0.1:5266" # URL of your running MentisRuntime service

# --- Setup Instructions ---
echo "### Mentis Sandbox Manual API Test Script ###"
echo ""
echo "This script will guide you through testing commands in a Mentis Sandbox."
echo "Please ensure the following prerequisites are met:"
echo "  1. Docker daemon is running."
echo "  2. The MentisRuntime Go service is running (listening on ${BASE_URL})."
echo "     (If not running, start it, e.g., 'go run ./go/mentisruntime/main.go')"
echo ""
echo "------------------------------------------------------------------"
echo "Step 1: Create a Sandbox (if you don't have an ID ready)"
echo "------------------------------------------------------------------"
echo "Run this curl command in your terminal to create a new sandbox in the 'default' space:"
echo ""
# Display the command clearly
cat << EOF
curl -X POST \\
  ${BASE_URL}/v1/spaces/default/sandboxes \\
  -H "Content-Type: application/json" \\
  -d '{}'
EOF
echo ""
echo "The command above will output JSON. Look for the 'sandbox_id' field and copy its value."
echo "Example output:"
echo '{'
echo '  "sandbox_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",'
echo '  "container_id": "...",'
echo '  "agent_url": "http://...",'
echo '  "is_running": true,'
echo '  "space_id": "default"'
echo '}'
echo ""

# --- Prompt for the Sandbox ID ---
read -p "Paste the 'sandbox_id' you obtained here: " SANDBOX_ID

# --- Validate Sandbox ID ---
if [ -z "$SANDBOX_ID" ]; then
  echo ""
  echo "ERROR: Sandbox ID cannot be empty. Please run the curl command above and provide the ID."
  exit 1
fi
echo ""
echo "Using Sandbox ID: $SANDBOX_ID"
echo ""

# --- WebSocket Monitoring Instruction ---
echo "------------------------------------------------------------------"
echo "Step 2: Monitor WebSocket Stream"
echo "------------------------------------------------------------------"
echo "IMPORTANT: Open a NEW, SEPARATE terminal window now and run the following"
echo "command to see the real-time output from the sandbox:"
echo ""
echo "websocat ws://127.0.0.1:5266/v1/sandboxes/$SANDBOX_ID/stream"
echo ""
echo "Keep that terminal window visible."
echo ""

# --- Wait for User Confirmation ---
echo "------------------------------------------------------------------"
echo "Step 3: Start Tests"
echo "------------------------------------------------------------------"
read -p ">>> Press Enter here when 'websocat' is running in the other terminal and you are ready to begin sending commands <<<"

echo ""
echo "--- Starting Test Suite for Sandbox ID: $SANDBOX_ID ---"
echo "--- API Base URL: $BASE_URL ---"
echo ""
sleep 1

# --- Helper Function to run a test via curl ---
# Usage: run_test <test_number> <description> <endpoint_suffix> <json_payload>
run_test() {
  local test_num=$1
  local description=$2
  local endpoint_suffix=$3 # e.g., "tools:run_shell_command" or "tools:run_ipython_cell"
  local payload=$4
  local space_id="default" # Assuming tests run in the default space
  # Construct the correct URL including the space
  local url="${BASE_URL}/v1/spaces/${space_id}/sandboxes/${SANDBOX_ID}/${endpoint_suffix}"

  echo "--- Test $test_num: $description ---"
  echo "POST $url"
  echo "Payload: $payload"
  echo "Sending request..."

  # Execute curl command and capture HTTP status code
  http_status=$(curl -X POST "$url" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --silent --output /dev/null \
    -w "%{http_code}") # Write only HTTP status code to stdout

  # Check curl exit status and HTTP status code
  if [ $? -ne 0 ]; then
    echo "WARNING: curl command itself failed for Test $test_num."
  elif [[ "$http_status" -ne 200 && "$http_status" -ne 202 ]]; then # Accept 200 or 202 (Accepted)
    echo "WARNING: API request for Test $test_num returned HTTP Status $http_status"
  else
    echo "API request sent successfully (HTTP $http_status). Check websocat output for execution results."
  fi

  echo "" # Newline for readability
  # Add a small delay to allow observation of results before the next command
  # Adjust sleep duration as needed
  sleep 2
}

# --- Test Cases ---
echo "=== Section: Basic Execution ==="
run_test 1 "Basic Shell Command" "tools:run_shell_command" '{"command": "echo \"Test 1: Basic Shell OK\""}'
run_test 2 "Basic IPython Execution" "tools:run_ipython_cell" '{"code": "print(\"Test 2: Basic IPython OK\")"}'
run_test 3 "Shell Command with Args & Check WD" "tools:run_shell_command" '{"command": "ls -l /work && echo \"(Expected WD: /work)\""}' # Check listing in /work
run_test 4 "IPython Multi-line Code & Sys Info" "tools:run_ipython_cell" '{"code": "import sys\nprint(f\"Test 4: Python Version: {sys.version_info.major}.{sys.version_info.minor}\")"}'

echo "=== Section: State Persistence (IPython) ==="
run_test 5 "IPython State - Set Variable" "tools:run_ipython_cell" '{"code": "test_var_5 = 123\nprint(f\"Test 5: Set test_var_5 = {test_var_5}\")"}'
run_test 6 "IPython State - Get Variable" "tools:run_ipython_cell" '{"code": "try:\n    print(f\"Test 6: Get test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 6: Variable test_var_5 not found!\")"}'
run_test 7 "IPython State - Modify Variable" "tools:run_ipython_cell" '{"code": "try:\n    test_var_5 += 1\n    print(f\"Test 7: Modified test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 7: Variable test_var_5 not found!\")"}'
run_test 8 "IPython State - Check Modified Variable" "tools:run_ipython_cell" '{"code": "try:\n    print(f\"Test 8: Check modified test_var_5 = {test_var_5}\")\nexcept NameError:\n    print(\"Test 8: Variable test_var_5 not found!\")"}'

echo "=== Section: Libraries and Computation ==="
run_test 9 "IPython NumPy Basic" "tools:run_ipython_cell" '{"code": "import numpy as np\na = np.array([1, 2, 3])\nprint(f\"Test 9: NumPy array: {a}\")"}'
run_test 10 "IPython NumPy Calculation" "tools:run_ipython_cell" '{"code": "import numpy as np\narr = np.arange(6).reshape((2, 3))\nprint(f\"Test 10: NumPy sum: {np.sum(arr)}\")"}'
run_test 11 "IPython Standard Library (datetime)" "tools:run_ipython_cell" '{"code": "import datetime\nprint(f\"Test 11: Current time (UTC): {datetime.datetime.utcnow()}\")"}'
run_test 12 "IPython Standard Library (json)" "tools:run_ipython_cell" '{"code": "import json\ndata = {\"key\": \"value\", \"num\": 1}\nprint(f\"Test 12: JSON dump: {json.dumps(data)}\")"}'

echo "=== Section: File System Operations (in /work) ==="
run_test 13 "Shell Create File in /work" "tools:run_shell_command" '{"command": "echo \"Test 13 Content\" > /work/test13.txt && echo \"Test 13: File created in /work\""}'
run_test 14 "Shell Read File from /work" "tools:run_shell_command" '{"command": "cat /work/test13.txt"}'
run_test 15 "IPython Read File from /work" "tools:run_ipython_cell" '{"code": "try:\n    with open(\"/work/test13.txt\", \"r\") as f:\n        content = f.read().strip()\n        print(f\"Test 15: Read from IPython: {content}\")\nexcept FileNotFoundError:\n    print(\"Test 15: File /work/test13.txt not found!\")"}'
run_test 16 "Shell Append to File in /work" "tools:run_shell_command" '{"command": "echo \"Appended Content\" >> /work/test13.txt && echo \"Test 16: Appended to file in /work\""}'
run_test 17 "IPython Read Appended File from /work" "tools:run_ipython_cell" '{"code": "try:\n    with open(\"/work/test13.txt\", \"r\") as f:\n        content = f.read()\n        print(f\"Test 17: Read appended content from /work:\\n{content}\")\nexcept FileNotFoundError:\n    print(\"Test 17: File /work/test13.txt not found!\")"}'
run_test 18 "Shell List /work Directory" "tools:run_shell_command" '{"command": "ls -la /work"}'

echo "=== Section: Environment Variables ==="
run_test 19 "Shell Set ENV VAR (Export likely won't persist across calls)" "tools:run_shell_command" '{"command": "export TEST_VAR_19=\"ShellValue\" && echo \"Test 19: Set TEST_VAR_19 (may not persist)\""}'
run_test 20 "IPython Read ENV VAR (Set by previous Shell export)" "tools:run_ipython_cell" '{"code": "import os\nval = os.environ.get(\"TEST_VAR_19\", \"Not Set\")\nprint(f\"Test 20: IPython reads TEST_VAR_19: {val}\")"}' # Expected: "Not Set"
run_test 21 "IPython Set ENV VAR" "tools:run_ipython_cell" '{"code": "import os\nos.environ[\"TEST_VAR_21\"] = \"IPythonValue\"\nprint(f\"Test 21: IPython set TEST_VAR_21\")"}'
run_test 22 "IPython Read ENV VAR (Set by previous IPython call)" "tools:run_ipython_cell" '{"code": "import os\nval = os.environ.get(\"TEST_VAR_21\", \"Not Set\")\nprint(f\"Test 22: IPython reads TEST_VAR_21: {val}\")"}' # Expected: "IPythonValue"

echo "=== Section: Error Handling ==="
run_test 23 "Shell Non-existent Command" "tools:run_shell_command" '{"command": "this_command_does_not_exist_xyz"}'
run_test 24 "Shell Command Non-Zero Exit" "tools:run_shell_command" '{"command": "ls /nonexistent_directory_abc ; exit $?"}' # Ensure exit code is non-zero
run_test 25 "IPython NameError" "tools:run_ipython_cell" '{"code": "print(undefined_variable_for_test_25)"}'
run_test 26 "IPython SyntaxError" "tools:run_ipython_cell" '{"code": "print(\"Test 26: Syntax Error\" oops)"}'
run_test 27 "IPython ZeroDivisionError" "tools:run_ipython_cell" '{"code": "result = 1 / 0\nprint(result)"}'

echo "=== Section: Large Output (Reduced) ==="
run_test 28 "Shell Large Output (Reduced)" "tools:run_shell_command" '{"command": "for i in $(seq 1 20); do echo \"Shell Line $i\"; sleep 0.05; done"}' # Added small sleep
run_test 29 "IPython Large Output (Reduced)" "tools:run_ipython_cell" '{"code": "import time\nfor i in range(1, 21):\n    print(f\"IPython Line {i}\")\n    time.sleep(0.05)"}' # Added small sleep

echo "=== Section: System Info / Verification ==="
run_test 30 "Shell System Info" "tools:run_shell_command" '{"command": "echo \"--- Sys Info ---\" && uname -a && echo \"--- Python Info ---\" && python3 --version && echo \"--- IPython Info ---\" && ipython --version && echo \"--- Working Dir ---\" && pwd && echo \"--- User ---\" && whoami"}'

# === Bonus: Example to Verify Agent Code (Adjust path if needed) ===
# run_test 31 "Verify Agent Code Snippet" "tools:run_shell_command" '{"command": "grep -A 3 \"send_observation(runtime_observation_url\" /sandbox/mentis_executor/main.py || echo \"Code snippet not found\""}' # Assumes code is in /sandbox


echo ""
echo "--- Test Suite Completed for Sandbox ID: $SANDBOX_ID ---"
echo "--- PLEASE CHECK THE WEBSOCAT OUTPUT IN THE OTHER TERMINAL ---"
echo "--- Compare the output there against the description of each test run above. ---"