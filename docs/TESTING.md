# Testing Mentis Sandbox

This document outlines how to run the different test suites for the Mentis Sandbox project.

## Prerequisites

Before running any tests, ensure you have the following installed and configured:

1.  **Go:** Version 1.22 or later (check with `go version`). Required for running the MentisRuntime server.
2.  **Docker:** Docker daemon must be running (check with `docker ps`). Required for creating sandbox containers.
3.  **Git:** For cloning the repository.
4.  **Make (Optional):** Used for convenience build commands (`make build/sandboxaid`, `make build-box-image`).
5.  **Python:** Version 3.8 or later (check with `python3 --version`). Required for the Python client library and its tests.
6.  **Python Environment & Dependencies:** It's recommended to use a virtual environment. Install the client and its test dependencies:
    ```bash
    # From the <project_root>/python directory
    python3 -m venv venv
    source venv/bin/activate
    # Install client in editable mode and test dependencies
    pip install -e .[test] 
    # Ensure pytest is installed
    pip install pytest websockets # Add websockets if needed by client for tests
    ```
7.  **Go Dependencies:** Download necessary Go modules:
    ```bash
    # From the <project_root>/go directory
    go mod download
    ```
8.  **MentisRuntime Executable (`sandboxaid`):** Build the Go server executable:
    ```bash
    # From the project root directory
    make build/sandboxaid
    # Or: cd go && go build -o ../bin/sandboxaid ./mentisruntime/main.go && cd ..
    ```
9.  **Test Data Files (for Go E2E Tests):** Ensure the JSON test case files required by the Go tests are present at `<project_root>/test/e2e/` (including `sandbox.json` and the `cases/` subdirectory). If you deleted them previously, restore them from Git or recreate them based on earlier versions.

## 1. Running Python E2E Tests (Recommended Primary Suite)

This suite (`python/test/e2e_test.py`) uses `pytest` and the `mentis_client` library to perform end-to-end tests covering sandbox creation, command execution (Shell & IPython), state persistence, error handling, space management, and asynchronous observation handling via WebSockets. It is run via the `e2e/run.sh` script.

**Steps:**

1.  **Ensure No Conflicting Server:** Make sure no other MentisRuntime instance is running on the default port (usually 5266), *unless* you plan to skip the embedded test (see note below).
2.  **Navigate to Project Root:** Open your terminal in the root directory of the `sandboxai` project.
3.  **Run the Script:**
    ```bash
    ./e2e/run.sh
    ```
    *(Ensure the script has execute permissions: `chmod +x e2e/run.sh`)*

**What `e2e/run.sh` does:**

* Checks for the `sandboxaid` executable.
* Starts the `sandboxaid` Go Runtime server in the background, redirecting its logs to `sandboxaid_stdout.log` and `sandboxaid_stderr.log`.
* Waits for the server to become healthy.
* Sets the `MENTIS_RUNTIME_URL` environment variable for the tests.
* Changes to the `python/` directory.
* Executes `pytest test/e2e_test.py` (using `uv run` if available).
* Changes back to the project root.
* Reports the `pytest` exit code.
* If tests failed, it provides debugging hints and prints the server logs (`sandboxaid_stdout.log`, `sandboxaid_stderr.log`).
* Automatically stops the `sandboxaid` server upon script exit (via `trap`).
