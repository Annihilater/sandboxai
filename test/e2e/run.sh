#!/bin/bash

# set -eu  # <-- 移除 'e' 标志，这样 pytest 失败时脚本不会立即退出
set -u   # <-- 保留 'u' 标志，处理未定义变量

repo_root=$(git rev-parse --show-toplevel)
echo "Repo root: $repo_root"
sandboxaid_executable="$repo_root/bin/sandboxaid"

# Check if sandboxaid executable exists
if [ ! -f "$sandboxaid_executable" ]; then
    echo "Error: sandboxaid executable not found at $sandboxaid_executable"
    echo "Please build the Go runtime first (e.g., using 'make build/sandboxaid')."
    exit 1
fi

# Add bin directory to PATH (optional, but kept for consistency if other tools are used)
export PATH="$PATH:$repo_root/bin"

# --- Start sandboxaid in the background ---
echo "Starting sandboxaid server..."
SANDBOXAID_PORT=${SANDBOXAID_PORT:-5266}
SANDBOXAID_HOST=${SANDBOXAID_HOST:-localhost}
RUNTIME_BASE_URL="http://${SANDBOXAID_HOST}:${SANDBOXAID_PORT}"

# 启动 Go 服务并将标准错误重定向到文件或 /dev/null，避免干扰 pytest 输出
$sandboxaid_executable > sandboxaid_stdout.log 2> sandboxaid_stderr.log &
sandboxaid_pid=$!
echo "sandboxaid started with PID $sandboxaid_pid (stdout/stderr redirected to files)"

# --- Cleanup function to stop sandboxaid ---
cleanup() {
    echo "Stopping sandboxaid (pid $sandboxaid_pid)..."
    # Use kill -TERM for graceful shutdown, wait a bit, then force if needed
    if kill -0 $sandboxaid_pid > /dev/null 2>&1; then
        kill -TERM $sandboxaid_pid
        # Wait up to 5 seconds for graceful shutdown
        for _ in {1..5}; do
            if ! kill -0 $sandboxaid_pid > /dev/null 2>&1; then
                echo "sandboxaid stopped gracefully."
                return
            fi
            sleep 1
        done
        echo "sandboxaid did not stop gracefully, sending SIGKILL..."
        kill -KILL $sandboxaid_pid > /dev/null 2>&1 || true # Ignore error if already stopped
    else
         echo "sandboxaid already stopped."
    fi
    echo "sandboxaid stopped."
}
# Trap common exit signals AND script exit (EXIT)
trap cleanup EXIT INT TERM

# --- Wait for sandboxaid to start ---
health_url="${RUNTIME_BASE_URL}/v1/healthz"
echo -n "Waiting up to 15s for sandboxaid at ${health_url}"
for i in {1..15}; do
    echo -n "."
    # Temporarily disable exit on error just for curl
    set +e
    curl --fail --silent --max-time 1 ${health_url} >/dev/null 2>&1
    curl_exit_code=$?
    # Re-enable stricter error checking if needed (or leave off if set -u is enough)
    # set -e
    set -u

    if [ $curl_exit_code -eq 0 ]; then
        echo ""
        echo "sandboxaid is healthy."
        break
    elif [ $i -eq 15 ]; then
        echo ""
        echo "Error: sandboxaid failed to start or become healthy after 15 seconds."
        echo "Check sandboxaid_stderr.log for errors."
        exit 1 # Exit if server fails to start
    fi
    sleep 1
done

# --- Set environment variable for tests ---
export MENTIS_RUNTIME_URL="${RUNTIME_BASE_URL}"
echo "MENTIS_RUNTIME_URL set to: ${MENTIS_RUNTIME_URL}"

# --- Run Python mentis_client tests ---
echo "Starting Python mentis_client tests..."
cd "$repo_root/python"

pytest_command="pytest test_mentis_client.py -v -s \"$@\""
# Check if uv is available
if command -v uv &> /dev/null; then
    pytest_command="uv run $pytest_command"
elif ! command -v pytest &> /dev/null; then
     echo "Error: 'pytest' or 'uv' command not found. Please install one."
     exit 1
fi

echo "Running command: $pytest_command"
# Execute pytest command - allow it to fail without exiting script
eval $pytest_command
test_exit_code=$?

cd "$repo_root" # Return to repo root

echo "-----------------------------------------------------"
echo "Pytest finished with exit code $test_exit_code."
echo "-----------------------------------------------------"

# --- Add Debugging Information ---
if [ $test_exit_code -ne 0 ]; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "!!! Tests failed. Providing debug information: !!!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    echo "Listing all Docker containers (including stopped ones):"
    docker ps -a
    echo ""
    echo "Instructions for debugging:"
    echo "1. Look at the Go Manager logs (sandboxaid_stderr.log or console output if not redirected) around the time of the test failure."
    echo "2. Find log lines like 'Container created ... containerID=\"<container_id>\" ... sandboxID=\"<sandbox_id>\"'."
    echo "3. Correlate the sandboxID with the failing Pytest output (if available)."
    echo "4. Use 'docker logs <container_id>' with the ID found in step 2 to view the Python Agent logs for that specific container."
    echo "5. Look for Python tracebacks or FastAPI/Uvicorn errors within the agent logs around the time the 500 error occurred."
    echo ""
    echo "(The sandboxaid Go server (PID $sandboxaid_pid) will be stopped by the cleanup trap shortly after this script finishes)."
    echo ""
fi
# --- End Debugging Information ---


# Exit with the original pytest exit code
exit $test_exit_code