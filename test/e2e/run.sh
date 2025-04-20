#!/bin/bash

set -eu

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
# Ensure SANDBOXAID_HOST and SANDBOXAID_PORT are set if needed, otherwise defaults apply
SANDBOXAID_PORT=${SANDBOXAID_PORT:-5266} # Changed default port to 5266
SANDBOXAID_HOST=${SANDBOXAID_HOST:-localhost}
RUNTIME_BASE_URL="http://${SANDBOXAID_HOST}:${SANDBOXAID_PORT}"

$sandboxaid_executable &
sandboxaid_pid=$!
echo "sandboxaid started with PID $sandboxaid_pid"

# --- Cleanup function to stop sandboxaid ---
cleanup() {
    echo "Stopping sandboxaid (pid $sandboxaid_pid)..."
    # Use kill -TERM for graceful shutdown, wait a bit, then force if needed
    kill -TERM $sandboxaid_pid > /dev/null 2>&1
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
    echo "sandboxaid stopped forcefully."
}
trap cleanup EXIT INT TERM # Trap common exit signals

# --- Wait for sandboxaid to start ---
health_url="${RUNTIME_BASE_URL}/v1/healthz"
echo -n "Waiting for sandboxaid at ${health_url}"
for i in {1..15}; do # Increased wait time slightly
    echo -n "."
    set +e # Temporarily disable exit on error for curl
    curl --fail --silent --max-time 1 ${health_url} >/dev/null 2>&1
    curl_exit_code=$?
    set -e # Re-enable exit on error
    if [ $curl_exit_code -eq 0 ]; then
        echo ""
        echo "sandboxaid is healthy."
        break
    elif [ $i -eq 15 ]; then
        echo ""
        echo "Error: sandboxaid failed to start or become healthy after 15 seconds."
        exit 1
    fi
    sleep 1
done

# --- Set environment variable for tests ---
export MENTIS_RUNTIME_URL="${RUNTIME_BASE_URL}" # Use the URL the tests expect
echo "MENTIS_RUNTIME_URL set to: ${MENTIS_RUNTIME_URL}"

# --- Run Python mentis_client tests ---
echo "Starting Python mentis_client tests..."
cd "$repo_root/python"

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Warning: 'uv' command not found. Attempting to run pytest directly."
    # Check if pytest is available
    if ! command -v pytest &> /dev/null; then
        echo "Error: 'pytest' command not found. Please install uv or pytest."
        exit 1
    fi
    # Run pytest directly - Corrected path
    pytest test_mentis_client.py -v -s "$@" # Pass any extra args to pytest
else
    # Run pytest using uv - Corrected path
    uv run pytest test_mentis_client.py -v -s "$@" # Pass any extra args to pytest
fi

test_exit_code=$?
cd "$repo_root" # Return to repo root

echo "Python tests finished with exit code $test_exit_code."

# Exit with the pytest exit code
exit $test_exit_code
