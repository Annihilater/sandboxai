# Makefile

# Variables
GO_CMD=go
GO_BUILD=$(GO_CMD) build
GO_TEST=$(GO_CMD) test
GO_CLEAN=$(GO_CMD) clean
PYTHON_DIR=python
GO_DIR=go
BIN_DIR=bin
SANDBOXAID_EXEC=$(BIN_DIR)/sandboxaid
TEST_SCRIPT=test/e2e/run.sh
BOX_IMG := mentisai/sandboxai-box:$(shell git describe --tags --dirty --always)
BOX_IMG_LATEST := mentisai/sandboxai-box:latest

# Default target
.PHONY: all
all: build/sandboxaid

# --- Go Build ---
.PHONY: build/sandboxaid
build/sandboxaid:
	@echo "Building sandboxaid Go executable..."
	@mkdir -p $(BIN_DIR)
	@echo "Changing directory to $(GO_DIR) for build..."
	cd $(GO_DIR) && $(GO_BUILD) -o ../$(SANDBOXAID_EXEC) ./mentisruntime/main.go
	@echo "sandboxaid built at $(SANDBOXAID_EXEC)"

# --- Docker Image Build ---
.PHONY: build-box-image
build-box-image:
	docker build . -f box.Dockerfile --progress=plain -t $(BOX_IMG) -t $(BOX_IMG_LATEST)
	@echo "Built two images: $(BOX_IMG) and $(BOX_IMG_LATEST)"

# --- Go Tests ---
.PHONY: test/go
test/go:
	@echo "Running Go tests..."
	cd $(GO_DIR) && $(GO_TEST) -v ./...
	@echo "Go tests finished."

# --- Python Tests (using E2E script) ---
.PHONY: test/python
test/python: build/sandboxaid # Ensure sandboxaid is built before running tests
	@echo "Running Python mentis_client tests via E2E script..."
	@if [ ! -f "$(TEST_SCRIPT)" ]; then \
		echo "Error: Test script $(TEST_SCRIPT) not found."; \
		exit 1; \
	fi
	@chmod +x $(TEST_SCRIPT) # Ensure script is executable
	./$(TEST_SCRIPT) # Execute the script which handles server start/stop and pytest
	@echo "Python tests finished."

# --- Combined Tests ---
.PHONY: test
test: test/go test/python

# --- Clean ---
.PHONY: clean
clean:
	@echo "Cleaning build artifacts and Go cache..."
	@rm -f $(SANDBOXAID_EXEC)
	$(GO_CLEAN) -cache -testcache ./...
	@echo "Cleaning Python cache..."
	@find $(PYTHON_DIR) -type f -name '*.pyc' -delete
	@find $(PYTHON_DIR) -type d -name '__pycache__' -delete
	@rm -rf $(PYTHON_DIR)/.pytest_cache
	@echo "Clean finished."

# --- UV Installation ---
UV := $(shell which uv)

.PHONY: install-uv
install-uv:
ifndef UV
	curl -LsSf https://astral.sh/uv/install.sh | sh
else
	@echo "uv is already installed at $(UV)"
endif

# --- Additional Build & Test Targets ---
.PHONY: build-sandboxaid
build-sandboxaid:
	cd $(GO_DIR) && $(GO_BUILD) -o ../$(BIN_DIR)/sandboxaid ./mentisruntime/main.go
	mkdir -p $(PYTHON_DIR)/sandboxai/bin/
	cp $(BIN_DIR)/sandboxaid $(PYTHON_DIR)/sandboxai/bin/

.PHONY: test-unit
test-unit:
	cd $(GO_DIR) && $(GO_TEST) -v ./api/...
	cd $(GO_DIR) && $(GO_TEST) -v ./client/...
	# 原路径不存在，已修正为 mentisruntime
	cd $(GO_DIR) && $(GO_TEST) -v ./mentisruntime/...

.PHONY: test-e2e
test-e2e: install-uv build/sandboxaid build-box-image
	BOX_IMAGE=$(BOX_IMG) ./$(TEST_SCRIPT)

.PHONY: lint-python
lint-python: install-uv
	cd $(PYTHON_DIR) && uv run ruff check

.PHONY: format-python
format-python: install-uv
	cd $(PYTHON_DIR) && uv run ruff format

.PHONY: format-python-check
format-python-check: install-uv
	cd $(PYTHON_DIR) && uv run ruff format --check \
	   || (echo "Please run 'uv run ruff format' to fix this formatting issue." && exit 1)

.PHONY: test-all
test-all: test-unit test-e2e lint-python format-python-check

# --- Code Generation ---
.PHONY: generate
generate: generate-go generate-python

.PHONY: generate-go
generate-go:
	# NOTE: 使用 "oapi-codegen/oapi-codegen" 代替 "openapitools/openapi-generator-cli"
	cd ./$(GO_DIR) && go generate ./...

# TODO: Register the datamodel-code-generator pip package with UV.
.PHONY: generate-python
generate-python:
	# 注意: 确保已安装 datamodel-code-generator
	datamodel-codegen \
		--input ./api/v1.yaml \
		--input-file-type openapi \
		--output ./$(PYTHON_DIR)/sandboxai/api/v1.py

# --- Help ---
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  all                  - Build the sandboxaid executable (default)"
	@echo "  build/sandboxaid     - Build the sandboxaid Go executable"
	@echo "  build-box-image      - Build Docker image for sandbox containers"
	@echo "  build-sandboxaid     - Alternative build for Python integration"
	@echo "  test/go              - Run Go unit/integration tests"
	@echo "  test/python          - Run Python mentis_client tests using the E2E script"
	@echo "  test                 - Run both Go and Python tests"
	@echo "  test-unit            - Run unit tests"
	@echo "  test-e2e             - Run end-to-end tests"
	@echo "  test-all             - Run all tests including linting"
	@echo "  lint-python          - Lint Python code"
	@echo "  format-python        - Format Python code"
	@echo "  format-python-check  - Check Python code formatting"
	@echo "  generate             - Generate code from API specifications"
	@echo "  generate-go          - Generate Go code"
	@echo "  generate-python      - Generate Python code"
	@echo "  install-uv           - Install uv Python package manager"
	@echo "  clean                - Remove build artifacts and cache files"
	@echo "  help                 - Show this help message"

