#!/bin/bash
# Filepath: e2e/run.sh (Rewritten to execute test/e2e_test.py)

# set -eu  # <-- Keep 'e' commented out to allow pytest failure without script exit
set -u   # <-- Keep 'u' for undefined variable check

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

# Start Go service and redirect stderr to a file to avoid cluttering pytest output
# Redirect stdout as well if it's noisy
echo "Redirecting sandboxaid stdout to sandboxaid_stdout.log and stderr to sandboxaid_stderr.log"
$sandboxaid_executable > sandboxaid_stdout.log 2> sandboxaid_stderr.log &
sandboxaid_pid=$!
echo "sandboxaid started with PID $sandboxaid_pid (stdout/stderr redirected to files)"

# --- Cleanup function to stop sandboxaid ---
cleanup() {
    echo "Running cleanup..."
    if [ -n "$sandboxaid_pid" ] && kill -0 $sandboxaid_pid > /dev/null 2>&1; then
        echo "Stopping sandboxaid (pid $sandboxaid_pid)..."
        # Use kill -TERM for graceful shutdown, wait a bit, then force if needed
        kill -TERM $sandboxaid_pid
        # Wait up to 5 seconds for graceful shutdown
        for _ in {1..5}; do
            if ! kill -0 $sandboxaid_pid > /dev/null 2>&1; then
                echo "sandboxaid stopped gracefully."
                sandboxaid_pid="" # Clear pid after stopping
                return
            fi
            sleep 1
        done
        echo "sandboxaid did not stop gracefully after 5s, sending SIGKILL..."
        kill -KILL $sandboxaid_pid > /dev/null 2>&1 || true # Ignore error if already stopped
        sandboxaid_pid="" # Clear pid
    else
         echo "sandboxaid already stopped or PID unknown."
    fi
    echo "Cleanup finished."
}
# Trap common exit signals AND script exit (EXIT)
trap cleanup EXIT INT TERM HUP

# --- Wait for sandboxaid to start ---
# Use the /v1/health endpoint which seems standard now
health_url="${RUNTIME_BASE_URL}/v1/health"
echo -n "Waiting up to 15s for sandboxaid health check at ${health_url}"
for i in {1..15}; do
    echo -n "."
    # Temporarily disable exit on error just for curl
    set +e
    # Use -f to fail on server errors (like 404), -s for silent, -L to follow redirects
    curl -fsSL --max-time 1 ${health_url} >/dev/null 2>&1
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
        echo "Check sandboxaid_stderr.log and sandboxaid_stdout.log for errors."
        exit 1 # Exit if server fails to start
    fi
    sleep 1
done

# --- Set environment variable for tests ---
export MENTIS_RUNTIME_URL="${RUNTIME_BASE_URL}"
echo "MENTIS_RUNTIME_URL set to: ${MENTIS_RUNTIME_URL}"

# --- Run Python mentis_client tests ---
echo "Starting Python mentis_client tests..."
# Change directory to where the python code resides relative to repo_root
cd "$repo_root/python/mentis_client"

pytest_command="pytest test/e2e_test.py -v -s \"$@\""

# Check if uv is available for running pytest in a virtual env (optional)
if command -v uv &> /dev/null; then
    # Assuming uv uses the project's pyproject.toml or requirements.txt
    # Ensure you are in the correct directory ('python') for uv run
    echo "Using 'uv run' to execute pytest..."
    pytest_command="uv run $pytest_command"
elif ! command -v pytest &> /dev/null; then
     # Check if pytest is available globally or in the current env
     echo "Error: 'pytest' or 'uv' command not found. Please install pytest or uv."
     exit 1
else
    echo "Using global/virtualenv 'pytest'..."
fi

echo "Running command: $pytest_command"
# Execute pytest command - allow it to fail without exiting script immediately
eval $pytest_command
test_exit_code=$?

# Return to the original directory (repo root)
cd "$repo_root"

echo "-----------------------------------------------------"
echo "Pytest finished with exit code $test_exit_code."
echo "-----------------------------------------------------"

# --- Add Debugging Information on Failure ---
if [ $test_exit_code -ne 0 ]; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "!!! Tests failed. Providing debug information: !!!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    echo "Listing all Docker containers (including stopped ones):"
    docker ps -a
    echo ""
    echo ">>> Contents of sandboxaid_stdout.log:"
    cat sandboxaid_stdout.log
    echo ">>> End of sandboxaid_stdout.log"
    echo ""
    echo ">>> Contents of sandboxaid_stderr.log:"
    cat sandboxaid_stderr.log
    echo ">>> End of sandboxaid_stderr.log"
    echo ""
    echo "Instructions for further debugging:"
    echo "1. Look at the Go Manager logs above (sandboxaid_stderr.log or console output if not redirected) around the time of the test failure."
    echo "2. Find log lines like 'Container created ... containerID=\"<container_id>\" ... sandboxID=\"<sandbox_id>\"'."
    echo "3. Correlate the sandboxID with the failing Pytest output (if available)."
    echo "4. Use 'docker logs <container_id>' with the ID found in step 2 to view the Python Agent logs for that specific container."
    echo "5. Look for Python tracebacks or FastAPI/Uvicorn errors within the agent logs around the time the error occurred."
    echo ""
    echo "(The sandboxaid Go server (PID $sandboxaid_pid) will be stopped by the cleanup trap shortly after this script finishes)."
    echo ""
fi
# --- End Debugging Information ---

# Exit with the original pytest exit code
exit $test_exit_code