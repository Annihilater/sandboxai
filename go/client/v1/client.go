// Filepath: client/v1/client.go (Corrected Version)
package v1

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	// Import the API types generated from your spec
	v1 "github.com/foreveryh/sandboxai/go/api/v1"
)

var ErrSandboxNotFound = fmt.Errorf("sandbox not found")

// Client represents a client for interacting with the SandboxAI API.
// See the OpenAPI spec for API details.
type Client struct {
	// BaseURL to send requests to, for example "http://localhost:5266".
	// IMPORTANT: This BaseURL should NOT include the /v1 path prefix itself.
	BaseURL string
	httpc   *http.Client
}

type ClientOption func(*Client)

// WithHTTPClient allows providing a custom http.Client.
func WithHTTPClient(httpClient *http.Client) ClientOption {
	return func(c *Client) {
		c.httpc = httpClient
	}
}

// NewClient creates a new API client.
// baseURL should be the root of the runtime service (e.g., "http://localhost:5266").
func NewClient(baseURL string, opts ...ClientOption) *Client {
	c := &Client{
		BaseURL: baseURL, // Store the base URL without /v1
	}
	for _, opt := range opts {
		opt(c)
	}
	if c.httpc == nil {
		c.httpc = http.DefaultClient
	}
	return c
}

// CheckHealth performs a health check against the runtime service.
func (c *Client) CheckHealth(ctx context.Context) error {
	// --- CORRECTED URL ---
	url := fmt.Sprintf("%s/v1/health", c.BaseURL) // Use /v1/health
	// --- END CORRECTION ---
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}

	resp, err := c.httpc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	// Health check usually returns 200 OK
	if err := validateResponse(resp, http.StatusOK); err != nil {
		return err
	}
	return nil
}

// CreateSandbox creates a new sandbox in the specified space.
func (c *Client) CreateSandbox(ctx context.Context, space string, request *v1.CreateSandboxRequest) (*v1.Sandbox, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return nil, err
	}

	// --- CORRECTED URL ---
	url := fmt.Sprintf("%s/v1/spaces/%s/sandboxes", c.BaseURL, space) // Added /v1
	// --- END CORRECTION ---
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	// Expect 201 Created on successful creation
	if err := validateResponse(resp, http.StatusCreated); err != nil {
		return nil, err
	}

	var response v1.Sandbox
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, err
	}
	return &response, nil
}

// GetSandbox retrieves details for a specific sandbox.
func (c *Client) GetSandbox(ctx context.Context, space, name string) (*v1.Sandbox, error) {
	// --- CORRECTED URL ---
	url := fmt.Sprintf("%s/v1/spaces/%s/sandboxes/%s", c.BaseURL, space, name) // Added /v1
	// --- END CORRECTION ---
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	// Handle 404 specifically
	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrSandboxNotFound
	}
	// Expect 200 OK on success
	if err := validateResponse(resp, http.StatusOK); err != nil {
		return nil, err
	}

	var response v1.Sandbox
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, err
	}
	return &response, nil
}

// DeleteSandbox deletes a specific sandbox.
func (c *Client) DeleteSandbox(ctx context.Context, space, name string) error {
	// --- CORRECTED URL ---
	url := fmt.Sprintf("%s/v1/spaces/%s/sandboxes/%s", c.BaseURL, space, name) // Added /v1
	// --- END CORRECTION ---
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, url, nil)
	if err != nil {
		return err
	}

	resp, err := c.httpc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	// Expect 204 No Content on successful deletion
	if err := validateResponse(resp, http.StatusNoContent); err != nil {
		// Check if it was a 404 (already deleted or never existed)
		if resp.StatusCode == http.StatusNotFound {
			return ErrSandboxNotFound // Return specific error for 404
		}
		return err // Return generic validation error for other statuses
	}

	return nil
}

// RunIPythonCell executes code in an IPython kernel within the sandbox.
// NOTE: This is the SYNCHRONOUS client method. It expects the server to
// potentially block and return the full result, which might not match the
// current ASYNCHRONOUS server behavior (which returns 202 Accepted + action_id).
// This client might need further changes if used against the async API.
func (c *Client) RunIPythonCell(ctx context.Context, space, name string, request *v1.RunIPythonCellRequest) (*v1.RunIPythonCellResult, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return nil, err
	}
	// --- CORRECTED URL ---
	url := fmt.Sprintf("%s/v1/spaces/%s/sandboxes/%s/tools:run_ipython_cell", c.BaseURL, space, name) // Added /v1
	// --- END CORRECTION ---
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	// !!! IMPORTANT: The server now returns 202 Accepted for async start.
	// This client expects 200 OK and tries to parse RunIPythonCellResult.
	// This part WILL LIKELY FAIL against the current server implementation.
	// For now, we fix the URL, but the expected status code needs review
	// based on whether this sync client should still be used/supported.
	// Let's keep expectedStatus=200 for now to match the original client code,
	// but it will likely fail the test assertion against the current server.
	if err := validateResponse(resp, http.StatusOK); err != nil { // Kept 200 OK based on original code
		// Check if it was 202 Accepted (which the *server* sends now)
		if resp.StatusCode == http.StatusAccepted {
			// Handle the 202 case - perhaps return nil or a specific indicator?
			// For now, let's return an error indicating the mismatch for the sync client.
			bodyBytes, _ := io.ReadAll(resp.Body)
			return nil, fmt.Errorf("received 202 Accepted (expected 200 OK for sync client); server started async execution. Response: %s", string(bodyBytes))
		}
		return nil, err // Return other validation errors
	}

	var response v1.RunIPythonCellResult
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, err
	}
	return &response, nil
}

// RunShellCommand executes a shell command within the sandbox.
// NOTE: Similar to RunIPythonCell, this is SYNCHRONOUS and expects 200 OK,
// which may mismatch the current server's 202 Accepted async behavior.
func (c *Client) RunShellCommand(ctx context.Context, space, name string, request *v1.RunShellCommandRequest) (*v1.RunShellCommandResult, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return nil, err
	}
	// --- CORRECTED URL ---
	url := fmt.Sprintf("%s/v1/spaces/%s/sandboxes/%s/tools:run_shell_command", c.BaseURL, space, name) // Added /v1
	// --- END CORRECTION ---
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	// !!! IMPORTANT: Server returns 202 Accepted. This client expects 200 OK.
	// Keep 200 OK for now based on original code, but expect test failures.
	if err := validateResponse(resp, http.StatusOK); err != nil { // Kept 200 OK
		// Check if it was 202 Accepted
		if resp.StatusCode == http.StatusAccepted {
			bodyBytes, _ := io.ReadAll(resp.Body)
			return nil, fmt.Errorf("received 202 Accepted (expected 200 OK for sync client); server started async execution. Response: %s", string(bodyBytes))
		}
		return nil, err // Return other validation errors
	}

	var response v1.RunShellCommandResult
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, err
	}
	return &response, nil
}

// validateResponse checks if the HTTP response has the expected status code.
func validateResponse(resp *http.Response, expectedStatus int) error {
	if resp.StatusCode != expectedStatus {
		// Read body for detailed error message if possible
		plainBody, _ := io.ReadAll(resp.Body) // Read body only on error
		return fmt.Errorf("expected status %d, got %d: %s", expectedStatus, resp.StatusCode, string(plainBody))
	}
	return nil
}