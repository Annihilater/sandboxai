package manager

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/docker/docker/api/types" // Keep for ContainerJSON
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image" // Keep for PullOptions
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
	"github.com/docker/go-connections/nat"
	"github.com/google/uuid"

	"github.com/foreveryh/sandboxai/go/mentisruntime/ws"
)

// Define package-level errors
var (
	ErrSpaceNotFound     = errors.New("space not found")
	ErrSpaceNameConflict = errors.New("space name conflict")
	ErrSandboxNotFound   = errors.New("sandbox not found")
)

// SpaceState represents the state of a space
type SpaceState struct {
	ID          string
	Name        string
	Description string
	CreatedAt   time.Time
	UpdatedAt   time.Time
	Metadata    map[string]interface{}
	Sandboxes   map[string]*SandboxState // Map sandboxID to its state
}

// SandboxState represents the state of a sandbox
type SandboxState struct {
	ID          string `json:"sandbox_id"` // Changed JSON tag back to sandbox_id
	ContainerID string `json:"container_id,omitempty"` // Add JSON tags for consistency
	AgentURL    string `json:"agent_url,omitempty"`    // Add JSON tags for consistency
	IsRunning   bool   `json:"is_running"`           // Add JSON tags for consistency
	SpaceID     string `json:"space_id,omitempty"`     // Add JSON tags for consistency
	// Add other relevant state fields
}

type SandboxManager struct {
	mu           sync.RWMutex
	sandboxes    map[string]*SandboxState  // Map sandboxID to its state
	httpClient   *http.Client
	logger       *slog.Logger
	dockerClient *client.Client // Docker client for container operations
	hub          *ws.Hub          // WebSocket Hub for broadcasting observations
	spaceManager *SpaceManager    // Add reference to SpaceManager
	scope        string           // Scope for managing containers
}

// NewSandboxManager creates a new SandboxManager.
func NewSandboxManager(ctx context.Context, dockerClient *client.Client, hub *ws.Hub, spaceManager *SpaceManager, logger *slog.Logger, scope string) (*SandboxManager, error) {
	m := &SandboxManager{
		sandboxes:    make(map[string]*SandboxState),
		httpClient:   &http.Client{Timeout: 10 * time.Second}, // Add a default timeout
		logger:       logger.With("component", "sandbox-manager"),
		dockerClient: dockerClient,
		hub:          hub,
		spaceManager: spaceManager, // Store SpaceManager
		scope:        scope,
	}

	// TODO: Consider reconciling existing Docker containers managed by this scope on startup?

	return m, nil
}

// SandboxExists checks if a sandbox with the given ID is known to the manager.
// This method implements the ws.SandboxChecker interface.
func (m *SandboxManager) SandboxExists(ctx context.Context, sandboxID string) (bool, error) {
	m.mu.RLock()
	_, exists := m.sandboxes[sandboxID]
	m.mu.RUnlock()
	// In this basic implementation, we don't return an error, just existence.
	// A more complex implementation might check Docker or other sources.
	return exists, nil
}

// InitiateAction starts an action (shell or ipython) asynchronously.
// It generates an action ID, validates the sandbox state, launches a goroutine
// for execution, and returns the action ID immediately.
func (m *SandboxManager) InitiateAction(ctx context.Context, sandboxID string, actionType string, payload map[string]interface{}) (string, error) {
	m.mu.RLock()
	state, exists := m.sandboxes[sandboxID]
	m.mu.RUnlock()

	if !exists || !state.IsRunning {
		return "", fmt.Errorf("sandbox %s not found or not running", sandboxID)
	}

	actionID := uuid.NewString()

	// Construct the request body for the internal agent
	requestPayload := map[string]interface{}{
		"action_id": actionID,
	}
	for k, v := range payload {
		requestPayload[k] = v // Copy original payload (command, code, etc.)
	}

	requestBody, err := json.Marshal(requestPayload)
	if err != nil {
		return "", fmt.Errorf("failed to marshal request body for agent: %w", err)
	}

	var agentURL string
	switch actionType {
	case "shell":
		agentURL = fmt.Sprintf("%s/tools:run_shell_command", state.AgentURL) // Corrected path
	case "ipython":
		agentURL = fmt.Sprintf("%s/tools:run_ipython_cell", state.AgentURL) // Corrected path
	default:
		return "", fmt.Errorf("unsupported action type: %s", actionType)
	}

	// Launch the goroutine to handle the actual execution and streaming
	m.logger.Debug("Initiating action goroutine", "sandboxID", sandboxID, "actionID", actionID, "actionType", actionType) // 添加这行
	go m.handleActionExecution(context.Background(), sandboxID, actionID, agentURL, requestBody, actionType)

	m.logger.Info("Action initiated", "sandboxID", sandboxID, "actionID", actionID, "actionType", actionType)
	return actionID, nil // Return immediately
}

// Observation types (Placeholders - define properly later)
type Observation struct {
	ObservationType string      `json:"observation_type"` // Corrected JSON tag
	ActionID        string      `json:"action_id"`        // Corrected JSON tag
	Timestamp       string      `json:"timestamp"`       // Corrected JSON tag
	Data            interface{} `json:"data,omitempty"`  // Corrected JSON tag
}

type StartObservationData struct {
	// Add relevant start data if needed
}

type StreamObservationData struct {
	Stream string `json:"stream"` // Corrected JSON tag
	Line   string `json:"line"`   // Corrected JSON tag
}

type ErrorObservationData struct {
	Error string `json:"error"` // Corrected JSON tag
}

type EndObservationData struct {
	ExitCode int    `json:"exit_code"`       // Corrected JSON tag
	Error    string `json:"error,omitempty"` // Corrected JSON tag
}

// AgentObservation defines the structure expected from the agent's streaming response lines.
type AgentObservation struct {
	Type     string          `json:"type"`               // Corrected JSON tag
	Stream   string          `json:"stream,omitempty"`   // Corrected JSON tag
	Line     string          `json:"line,omitempty"`     // Corrected JSON tag
	ExitCode *int            `json:"exit_code,omitempty"` // Corrected JSON tag
	Error    string          `json:"error,omitempty"`     // Corrected JSON tag
}

// handleActionExecution runs in a goroutine to execute the action via the internal agent.
// It only handles the initial request and immediate HTTP errors.
// Subsequent observations (stream, result) are handled by ReceiveInternalObservation.
func (m *SandboxManager) handleActionExecution(ctx context.Context, sandboxID, actionID, agentURL string, requestBody []byte, actionType string) {
	m.logger.Debug("Goroutine started for action", "sandboxID", sandboxID, "actionID", actionID, "actionType", actionType) 
	// Send StartObservation immediately via the Hub
	m.pushObservation(sandboxID, actionID, "start", StartObservationData{})

	req, err := http.NewRequestWithContext(ctx, "POST", agentURL, bytes.NewReader(requestBody))
	if err != nil {
		errMsg := fmt.Sprintf("Failed to create request to agent: %v", err)
		m.pushErrorObservation(sandboxID, actionID, errMsg)
		m.pushObservation(sandboxID, actionID, "end", EndObservationData{ExitCode: -1, Error: errMsg})
		return
	}
	req.Header.Set("Content-Type", "application/json")
	// We don't strictly need Accept header anymore if we don't read the body for observations
	// req.Header.Set("Accept", "application/x-ndjson") 

	resp, err := m.httpClient.Do(req)
	if err != nil {
		errMsg := fmt.Sprintf("Failed to execute action request via agent: %v", err)
		m.pushErrorObservation(sandboxID, actionID, errMsg)
		m.pushObservation(sandboxID, actionID, "end", EndObservationData{ExitCode: -1, Error: errMsg})
		return
	}
	defer resp.Body.Close()

	// Handle only immediate HTTP errors from the agent
	if resp.StatusCode >= 400 {
		bodyBytes, readErr := io.ReadAll(resp.Body)
		errorMsg := fmt.Sprintf("Agent returned error status %d", resp.StatusCode)
		if readErr == nil && len(bodyBytes) > 0 {
			errorMsg += fmt.Sprintf(": %s", string(bodyBytes))
		} else if readErr != nil {
			errorMsg += fmt.Sprintf(" (failed to read error body: %v)", readErr)
		}
		m.pushErrorObservation(sandboxID, actionID, errorMsg)
		m.pushObservation(sandboxID, actionID, "end", EndObservationData{ExitCode: -1, Error: errorMsg})
		return
	}

	// If status code is OK (e.g., 200, 202), the request was accepted by the agent.
	// Log this success and exit the goroutine.
	// The agent will now asynchronously send observations via the /internal/observations endpoint.
	m.logger.Info("Action request successfully sent to agent", "sandboxID", sandboxID, "actionID", actionID, "agentURL", agentURL, "statusCode", resp.StatusCode)

	// DO NOT read resp.Body here for observations.
	// Let ReceiveInternalObservation handle stream/result/end logic based on pushed data.
}

// pushObservation formats and sends an observation via the hub.
func (m *SandboxManager) pushObservation(sandboxID, actionID, obsType string, data interface{}) {
	obs := Observation{
		ObservationType: obsType, // Use the renamed field
		ActionID:        actionID,
		Timestamp:       time.Now().UTC().Format(time.RFC3339Nano), // Add current timestamp
		Data:            data,
	}

	jsonData, err := json.Marshal(obs)
	if err != nil {
		m.logger.Error("Failed to marshal observation", "error", err, "sandboxID", sandboxID, "actionID", actionID, "type", obsType)
		return
	}

	m.logger.Debug("Pushing observation via Hub", "sandboxID", sandboxID, "actionID", actionID, "type", obsType, "size", len(jsonData))
	// Send via Hub
	m.hub.SubmitBroadcast(sandboxID, jsonData)
}

// pushErrorObservation formats and sends an error observation.
func (m *SandboxManager) pushErrorObservation(sandboxID, actionID, errorMsg string) {
	m.logger.Error("Action error occurred", "sandboxID", sandboxID, "actionID", actionID, "error", errorMsg)
	m.pushObservation(sandboxID, actionID, "error", ErrorObservationData{Error: errorMsg})
}

// CreateSandbox creates and starts a new sandbox container within a specific space.
// It pulls the necessary image, creates and starts the container,
// discovers its IP address, performs a health check on the agent,
// and stores its state.
func (m *SandboxManager) CreateSandbox(ctx context.Context, spaceID string, imageArg string, command []string) (string, error) { // command is now []string
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check if space exists using SpaceManager
	_, err := m.spaceManager.GetSpace(ctx, spaceID)
	if err != nil {
		if errors.Is(err, ErrSpaceNotFound) {
			return "", ErrSpaceNotFound // Return the specific error
		} else {
			m.logger.Error("Failed to check space existence before creating sandbox", "spaceID", spaceID, "error", err)
			return "", fmt.Errorf("failed to verify space %s: %w", spaceID, err)
		}
	}

	sandboxID := uuid.NewString() // Generate a unique ID

	// Get image name from environment variable or use default
	imageName := imageArg
	if imageName == "" {
		imageName = os.Getenv("BOX_IMAGE")
		if imageName == "" {
			imageName = "mentisai/sandboxai-box:latest" // Default if no environment variable set
		}
	}
	m.logger.Debug("Using box image", "image", imageName)

	agentPortInt := 8000
	agentPortProto := "tcp"
	agentPortString := fmt.Sprintf("%d/%s", agentPortInt, agentPortProto)

	m.logger.Info("Creating sandbox", "sandboxID", sandboxID, "spaceID", spaceID, "image", imageName)

	// 1. Ensure image exists locally
	// Use a shorter timeout for image pull check/pull
	pullCtx, pullCancel := context.WithTimeout(ctx, 5*time.Minute)
	defer pullCancel()

	// First check if image exists locally
	inspectCtx, inspectCancel := context.WithTimeout(ctx, 10*time.Second)
	defer inspectCancel()
	_, _, errInspect := m.dockerClient.ImageInspectWithRaw(inspectCtx, imageName)
	if errInspect == nil {
		// Image exists locally, no need to pull
		m.logger.Info("Image exists locally, skipping pull", "image", imageName)
	} else {
		// Try to pull the image only if it doesn't exist locally
		m.logger.Info("Image not found locally, attempting to pull", "image", imageName)
		// Corrected: Use image.PullOptions{} instead of types.
		out, err := m.dockerClient.ImagePull(pullCtx, imageName, image.PullOptions{})
		if err != nil {
			m.logger.Error("Failed to pull image", "image", imageName, "error", err)
			return "", fmt.Errorf("failed to pull image %s: %w", imageName, err)
		}
		// IMPORTANT: Block and drain the output to ensure the pull completes before proceeding.
		// Discard the output, but log errors if reading fails.
		defer out.Close()
		if _, err = io.Copy(io.Discard, out); err != nil {
			m.logger.Error("Failed reading image pull output", "image", imageName, "error", err)
			return "", fmt.Errorf("failed reading image pull output for %s: %w", imageName, err)
		}
		m.logger.Info("Image pull completed", "image", imageName)
	}

	// Add an explicit check after pulling to ensure the image exists locally
	// Use a new context for this inspection to avoid using the already potentially cancelled inspectCtx
	inspectCtx2, inspectCancel2 := context.WithTimeout(ctx, 10*time.Second)
	defer inspectCancel2()
	_, _, errInspect2 := m.dockerClient.ImageInspectWithRaw(inspectCtx2, imageName)
	if errInspect2 != nil {
		m.logger.Error("Image inspect failed after pull", "image", imageName, "error", errInspect2)
		return "", fmt.Errorf("image %s not found locally after pull attempt: %w", imageName, errInspect2)
	}
	m.logger.Info("Image confirmed to exist locally", "image", imageName)

	// 2. Create the container
	containerName := fmt.Sprintf("sandboxai-%s-%s", m.scope, sandboxID)
	labels := map[string]string{
		"sandboxai.scope": m.scope,
		"sandboxai.id":    sandboxID,
		"sandboxai.space": spaceID, // Add space label
	}
	// Determine the host address Runtime is listening on, as seen from the container
	// Using host.docker.internal which works for Docker Desktop. Might need configuration for other environments.
	runtimeHost := "host.docker.internal"
	// Get the port Runtime is listening on (assuming it's passed via env var or default)
	runtimePort := os.Getenv("SANDBOXAID_PORT")
	if runtimePort == "" {
		runtimePort = "5266" // Default port used in main.go
	}
	internalObservationURL := fmt.Sprintf("http://%s:%s/v1/internal/observations/%s", runtimeHost, runtimePort, sandboxID)

	envVars := []string{
		fmt.Sprintf("SANDBOX_ID=%s", sandboxID),
		// Add other necessary env vars for the agent
		fmt.Sprintf("RUNTIME_OBSERVATION_URL=%s", internalObservationURL), // Add URL for agent to push observations
	}

	// Use a shorter timeout for container operations
	createCtx, createCancel := context.WithTimeout(ctx, 30*time.Second)
	defer createCancel()

	resp, err := m.dockerClient.ContainerCreate(
		createCtx,
		&container.Config{
			Image:        imageName,
			Labels:       labels,
			Env:          envVars,
			// Expose agent port
			ExposedPorts: nat.PortSet{nat.Port(agentPortString): struct{}{}},
			Tty:          true,
			OpenStdin:    true,
		},
		&container.HostConfig{
			NetworkMode: "bridge",
			// Re-introduce PortBindings for reliable connection
			PortBindings: nat.PortMap{
				nat.Port(agentPortString): []nat.PortBinding{
					{
						HostIP:   "0.0.0.0", // Bind to all host interfaces
						HostPort: "",      // Let Docker assign a random available port
					},
				},
			},
			// AutoRemove: true, // Consider adding this if desired
		},
		&network.NetworkingConfig{ // Default network is usually fine
		},
		nil, // Platform is usually nil
		containerName,
	)
	if err != nil {
		m.logger.Error("Failed to create container", "sandboxID", sandboxID, "name", containerName, "error", err)
		return "", fmt.Errorf("failed to create container: %w", err)
	}

	m.logger.Info("Container created", "sandboxID", sandboxID, "containerID", resp.ID, "name", containerName)

	// 3. Start the container
	startCtx, startCancel := context.WithTimeout(ctx, 15*time.Second)
	defer startCancel()
	if err := m.dockerClient.ContainerStart(startCtx, resp.ID, container.StartOptions{}); err != nil {
		m.logger.Error("Failed to start container", "sandboxID", sandboxID, "containerID", resp.ID, "error", err)
		// Attempt to remove the created container on start failure
		rmCtx, rmCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer rmCancel()
		if rmErr := m.dockerClient.ContainerRemove(rmCtx, resp.ID, container.RemoveOptions{Force: true}); rmErr != nil {
			m.logger.Error("Failed to remove container after start failure", "containerID", resp.ID, "removeError", rmErr)
		}
		return "", fmt.Errorf("failed to start container %s: %w", resp.ID, err)
	}
	
	// 添加诊断日志，查看容器是否成功启动
	m.logger.Info("Container started, checking status", "sandboxID", sandboxID, "containerID", resp.ID)
	
	// 立即检查容器状态，添加更多诊断信息
	diagCtx, diagCancel := context.WithTimeout(ctx, 5*time.Second)
	defer diagCancel()
	inspectAfterStart, diagErr := m.dockerClient.ContainerInspect(diagCtx, resp.ID)
	if diagErr != nil {
		m.logger.Warn("Failed to inspect container after start for diagnostics", "error", diagErr)
	} else {
		m.logger.Info("Container status after start", 
			"state", inspectAfterStart.State.Status,
			"running", inspectAfterStart.State.Running,
			"exitCode", inspectAfterStart.State.ExitCode,
			"error", inspectAfterStart.State.Error,
			"startedAt", inspectAfterStart.State.StartedAt)
	}

	// 4. Get Agent URL - Prioritize Port Mapping
	var agentURL string
	var containerIP string // Still try to get IP for logging/fallback
	var mappedPort string
	var inspectData types.ContainerJSON
	maxRetries := 5
	retryDelay := 1 * time.Second

	m.logger.Info("Waiting for container network setup and port mapping", "sandboxID", sandboxID, "containerID", resp.ID, "maxRetries", maxRetries)

	var lastInspectErr error
	for retry := 0; retry < maxRetries; retry++ {
		inspectCtxRetry, inspectCancelRetry := context.WithTimeout(ctx, 10*time.Second)
		inspectData, lastInspectErr = m.dockerClient.ContainerInspect(inspectCtxRetry, resp.ID)
		inspectCancelRetry()

		if lastInspectErr != nil {
			m.logger.Warn("Container inspect failed on retry", "retry", retry+1, "error", lastInspectErr)
			time.Sleep(retryDelay)
			continue
		}

		if !inspectData.State.Running {
			m.logger.Warn("Container not running yet", "retry", retry+1, "state", inspectData.State.Status)
			time.Sleep(retryDelay)
			continue
		}

		// Check for Port Mapping first
		if inspectData.NetworkSettings != nil && len(inspectData.NetworkSettings.Ports) > 0 {
			if portBindings, exists := inspectData.NetworkSettings.Ports[nat.Port(agentPortString)]; exists && len(portBindings) > 0 && portBindings[0].HostPort != "" {
				mappedPort = portBindings[0].HostPort
				m.logger.Info("Found mapped port", "containerPort", agentPortString, "hostPort", mappedPort)
				// Construct URL using localhost and mapped port
				agentURL = fmt.Sprintf("http://localhost:%s", mappedPort)
				break // Found the preferred URL
			}
		}

		m.logger.Info("Mapped port not found yet, retrying", "retry", retry+1, "maxRetries", maxRetries)
		time.Sleep(retryDelay)
	}

	// Fallback: If port mapping failed after retries, try container IP (less reliable)
	if agentURL == "" {
		m.logger.Warn("Could not find mapped port after retries, falling back to container IP method", "sandboxID", sandboxID)
		for retry := 0; retry < maxRetries; retry++ {
			inspectCtxIP, inspectCancelIP := context.WithTimeout(ctx, 10*time.Second)
			inspectDataIP, inspectErrIP := m.dockerClient.ContainerInspect(inspectCtxIP, resp.ID)
			inspectCancelIP()

			if inspectErrIP != nil {
				m.logger.Warn("Container inspect failed on IP fallback retry", "retry", retry+1, "error", inspectErrIP)
				time.Sleep(retryDelay)
				continue
			}

			if !inspectDataIP.State.Running {
				m.logger.Warn("Container not running on IP fallback retry", "retry", retry+1, "state", inspectDataIP.State.Status)
				time.Sleep(retryDelay)
				continue
			}

			if inspectDataIP.NetworkSettings != nil {
				if inspectDataIP.NetworkSettings.Networks != nil {
					for netName, netConfig := range inspectDataIP.NetworkSettings.Networks {
						if netConfig.IPAddress != "" {
							containerIP = netConfig.IPAddress
							m.logger.Info("Found container IP address (fallback)", "network", netName, "ip", containerIP)
							break
						}
					}
				}
				if containerIP == "" && inspectDataIP.NetworkSettings.IPAddress != "" {
					containerIP = inspectDataIP.NetworkSettings.IPAddress
					m.logger.Info("Using root NetworkSettings.IPAddress (fallback)", "ip", containerIP)
				}
			}

			if containerIP != "" {
				agentURL = fmt.Sprintf("http://%s:%d", containerIP, agentPortInt)
				break // Found fallback URL
			}

			m.logger.Info("No container IP found yet (fallback), retrying", "retry", retry+1, "maxRetries", maxRetries)
			time.Sleep(retryDelay)
		}
	}

	// Final check: If no URL could be constructed, fail
	if agentURL == "" {
		m.logger.Error("Failed to determine agent URL via port mapping or container IP after multiple retries", "sandboxID", sandboxID, "containerID", resp.ID)
		// Cleanup container
		rmCtx, rmCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer rmCancel()
		_ = m.dockerClient.ContainerRemove(rmCtx, resp.ID, container.RemoveOptions{Force: true})
		return "", fmt.Errorf("failed to determine agent URL for container %s after %d retries", resp.ID, maxRetries)
	}

	m.logger.Info("Constructed agent URL", "sandboxID", sandboxID, "agentURL", agentURL)

	// 6. Health Check (Add this step)
	healthCheckURL := fmt.Sprintf("%s/health", agentURL)
	agentReadyTimeout := 30 * time.Second // Adjust timeout as needed
	m.logger.Info("Starting agent health check", "sandboxID", sandboxID, "healthURL", healthCheckURL, "timeout", agentReadyTimeout)

	if err := m.waitForAgentReady(ctx, healthCheckURL, agentReadyTimeout); err != nil {
		m.logger.Error("Agent health check failed", "sandboxID", sandboxID, "healthURL", healthCheckURL, "error", err)
		// Cleanup container
		rmCtx, rmCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer rmCancel()
		_ = m.dockerClient.ContainerRemove(rmCtx, resp.ID, container.RemoveOptions{Force: true})
		return "", fmt.Errorf("agent health check failed: %w", err)
	}
	m.logger.Info("Agent health check successful", "sandboxID", sandboxID)

	// 7. 创建沙箱状态并存储 (Renumbered from 6)
	state := &SandboxState{
		ID:          sandboxID,
		ContainerID: resp.ID,
		AgentURL:    agentURL,
		IsRunning:   true,
		SpaceID:     spaceID,
	}

	// Add sandbox to manager's map
	m.sandboxes[sandboxID] = state

	// Add sandbox reference to the space using SpaceManager
	if err := m.spaceManager.addSandboxToSpace(spaceID, sandboxID, state); err != nil {
		// This should ideally not happen if space check passed, but handle defensively
		m.logger.Error("Failed to add sandbox reference to space after creating container", "spaceID", spaceID, "sandboxID", sandboxID, "error", err)
		// Consider cleanup? For now, log and continue, sandbox exists but space link failed.
	}

	m.logger.Info("Sandbox created and registered successfully", "sandboxID", sandboxID, "containerID", resp.ID, "agentURL", agentURL, "spaceID", spaceID)
	return sandboxID, nil
}

// Add the waitForAgentReady helper function (if not already present)
func (m *SandboxManager) waitForAgentReady(ctx context.Context, healthURL string, timeout time.Duration) error {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(500 * time.Millisecond) // Check every 500ms
	defer ticker.Stop()

	client := &http.Client{
		Timeout: 2 * time.Second, // Short timeout for each request
	}

	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("timeout waiting for agent to be ready: %w", ctx.Err())
		case <-ticker.C:
			req, err := http.NewRequestWithContext(ctx, "GET", healthURL, nil)
			if err != nil {
				m.logger.Debug("Failed to create HTTP request for health check", "healthURL", healthURL, "error", err)
				continue // Try again on next tick
			}

			resp, err := client.Do(req)
			if err != nil {
				m.logger.Debug("Agent health check failed (connection error)", "healthURL", healthURL, "error", err)
				continue // Try again on next tick
			}

			// Ensure body is closed
			io.Copy(io.Discard, resp.Body) // Drain the body
			resp.Body.Close()

			if resp.StatusCode >= 200 && resp.StatusCode < 300 {
				return nil // Success!
			}

			m.logger.Debug("Agent health check returned non-2xx status", "healthURL", healthURL, "statusCode", resp.StatusCode)
			// Try again on next tick
		}
	}
}

// DeleteSandbox stops and removes a sandbox container.
func (m *SandboxManager) DeleteSandbox(ctx context.Context, sandboxID string) error {
	m.logger.Info("Attempting to delete sandbox", "sandboxID", sandboxID)

	m.mu.Lock() // Lock for modifying sandboxes map
	state, exists := m.sandboxes[sandboxID]
	if !exists {
		m.mu.Unlock()
		m.logger.Warn("Sandbox not found in manager state during deletion attempt", "sandboxID", sandboxID)
		return ErrSandboxNotFound
	}
	spaceID := state.SpaceID // Get spaceID before deleting state
	m.mu.Unlock() // Unlock early, Docker operations can be slow

	// Attempt to stop the container
	stopTimeoutDuration := 5 * time.Second
	stopTimeoutSeconds := int(stopTimeoutDuration.Seconds()) // Convert to int seconds
	m.logger.Info("Stopping container", "containerID", state.ContainerID, "sandboxID", sandboxID, "timeout", stopTimeoutDuration)
	stopCtx, stopCancel := context.WithTimeout(ctx, stopTimeoutDuration+2*time.Second) // Give slightly more time
	defer stopCancel()
	err := m.dockerClient.ContainerStop(stopCtx, state.ContainerID, container.StopOptions{Timeout: &stopTimeoutSeconds})
	if err != nil {
		m.logger.Error("Failed to stop container, proceeding with removal attempt", "containerID", state.ContainerID, "sandboxID", sandboxID, "error", err)
	} else {
		m.logger.Info("Container stopped successfully", "containerID", state.ContainerID, "sandboxID", sandboxID)
	}

	// Attempt to remove the container
	m.logger.Info("Removing container", "containerID", state.ContainerID, "sandboxID", sandboxID)
	rmCtx, rmCancel := context.WithTimeout(ctx, 15*time.Second)
	defer rmCancel()
	err = m.dockerClient.ContainerRemove(rmCtx, state.ContainerID, container.RemoveOptions{
		Force: true,
	})
	if err != nil {
		m.logger.Error("Failed to remove container", "containerID", state.ContainerID, "sandboxID", sandboxID, "error", err)
		// Don't return yet, still need to clean up maps
	} else {
		m.logger.Info("Container removed successfully", "containerID", state.ContainerID, "sandboxID", sandboxID)
	}

	// Remove from manager's sandbox map
	m.mu.Lock()
	delete(m.sandboxes, sandboxID)
	m.mu.Unlock()

	// Remove sandbox reference from the space using SpaceManager
	if errSpace := m.spaceManager.removeSandboxFromSpace(spaceID, sandboxID); errSpace != nil {
		// Log error but don't make the overall deletion fail because of this
		m.logger.Error("Failed to remove sandbox reference from space", "spaceID", spaceID, "sandboxID", sandboxID, "error", errSpace)
	}

	m.logger.Info("Sandbox deleted successfully from manager state", "sandboxID", sandboxID)

	// Return the container removal error, if any
	if err != nil {
		return fmt.Errorf("failed to remove container %s: %w", state.ContainerID, err)
	}
	return nil
}

// GetSandbox retrieves the state of a specific sandbox by its ID.
func (m *SandboxManager) GetSandbox(ctx context.Context, sandboxID string) (*SandboxState, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	state, exists := m.sandboxes[sandboxID]
	if !exists {
		// Consider defining and returning a specific ErrSandboxNotFound error
		// return nil, fmt.Errorf("sandbox %s not found", sandboxID)
		return nil, ErrSandboxNotFound
	}

	// Optionally, inspect the container to get the latest status from Docker
	// This adds overhead but provides the most up-to-date info.
	// For now, we return the cached state.
	// _, err := m.dockerClient.ContainerInspect(ctx, state.ContainerID)
	// if err != nil {
	// 	 if client.IsErrNotFound(err) {
	// 		 // Container doesn't exist in Docker anymore, update our state?
	// 		 // This indicates a potential inconsistency.
	// 		 m.logger.Warn("Sandbox found in map but container not found in Docker", "sandboxID", sandboxID, "containerID", state.ContainerID)
	// 		 // Maybe remove from map here and return not found?
	// 		 // For now, return the state but log the inconsistency.
	// 	 } else {
	// 		 m.logger.Error("Failed to inspect container during GetSandbox", "sandboxID", sandboxID, "containerID", state.ContainerID, "error", err)
	// 		 // Return the cached state but maybe log the inspection error?
	// 	 }
	// }

	// Return a copy to prevent modification of the internal map state
	stateCopy := *state
	return &stateCopy, nil
}

// ReceiveInternalObservation receives raw observation data pushed from an agent.
func (m *SandboxManager) ReceiveInternalObservation(sandboxID string, observationBytes []byte) error {
	m.mu.RLock()
	_, exists := m.sandboxes[sandboxID]
	m.mu.RUnlock()

	if !exists {
		m.logger.Warn("Received internal observation for non-existent or deleted sandbox", "sandboxID", sandboxID)
		return nil // Don't return error to agent, just ignore
	}

	// Parse the observation to understand its type and potentially trigger actions (like sending 'end')
	// MODIFIED: Added ExitCode and Error fields (pointers) to capture top-level result/error data
	var obs struct {
		ObservationType string          `json:"observation_type"`
		ActionID        string          `json:"action_id"`
		Timestamp       time.Time       `json:"timestamp"`
		Data            json.RawMessage `json:"data"` // Keep data raw initially for flexibility
		ExitCode        *int            `json:"exit_code,omitempty"` // Added for result/error
		Error           *string         `json:"error,omitempty"`     // Added for result/error
	}

	if err := json.Unmarshal(observationBytes, &obs); err != nil {
		m.logger.Error("Failed to parse internal observation JSON", "sandboxID", sandboxID, "rawData", string(observationBytes), "error", err)
		// Decide if we should still broadcast the unparseable message? Maybe as an error type?
		// For now, log and potentially ignore, or broadcast the raw bytes if that was the intended behavior.
		// Let's broadcast the raw bytes if parsing fails, so client at least gets something.
		if m.hub != nil {
			m.logger.Warn("Broadcasting unparseable raw observation data", "sandboxID", sandboxID)
			m.hub.SubmitBroadcast(sandboxID, observationBytes)
		}
		return fmt.Errorf("failed to parse observation JSON: %w", err)
	}

	m.logger.Debug("Parsed internal observation struct",
		"sandboxID", sandboxID,
		"parsedActionID", obs.ActionID,
		"parsedObservationType", obs.ObservationType,
		"parsedTimestamp", obs.Timestamp,
		"rawData", string(observationBytes)) // Log raw data along with parsed info

	// Broadcast the parsed (original) bytes AFTER successful parsing
	if m.hub != nil {
		m.logger.Debug("Broadcasting successfully parsed observation data", "sandboxID", sandboxID, "type", obs.ObservationType)
		m.hub.SubmitBroadcast(sandboxID, observationBytes)
	}

	m.logger.Debug("Received internal observation", "sandboxID", sandboxID, "actionID", obs.ActionID, "type", obs.ObservationType)

	// Process specific observation types (e.g., 'result' triggers 'end')
	// MODIFIED: Pass the whole parsed obs struct to processParsedObservation
	if err := m.processParsedObservation(sandboxID, &obs); err != nil {
		// Log the error, but don't necessarily stop processing or return error to agent
		m.logger.Error("Error processing parsed observation", "sandboxID", sandboxID, "actionID", obs.ActionID, "type", obs.ObservationType, "error", err)
	}

	return nil
}

// processParsedObservation handles logic based on the observation type.
// MODIFIED: Takes the parsed observation struct pointer as input
func (m *SandboxManager) processParsedObservation(sandboxID string, obs *struct {
	ObservationType string          `json:"observation_type"`
	ActionID        string          `json:"action_id"`
	Timestamp       time.Time       `json:"timestamp"`
	Data            json.RawMessage `json:"data"`
	ExitCode        *int            `json:"exit_code,omitempty"`
	Error           *string         `json:"error,omitempty"`
}) error {
	switch obs.ObservationType {
	case "result":
		m.logger.Info("Received 'result' observation, sending 'end'", "sandboxID", sandboxID, "actionID", obs.ActionID)

		// MODIFIED: Use ExitCode directly from the parsed obs struct
		exitCode := 0 // Default to 0 if not present
		if obs.ExitCode != nil {
			exitCode = *obs.ExitCode
		} else {
			m.logger.Warn("Received 'result' observation without an exit_code, defaulting to 0", "sandboxID", sandboxID, "actionID", obs.ActionID)
		}
		m.sendEndObservation(sandboxID, obs.ActionID, exitCode)

	case "error":
		// Log agent-side errors
		errorMsg := "Unknown agent error"
		if obs.Error != nil {
			errorMsg = *obs.Error
		} else if obs.Data != nil && string(obs.Data) != "null" {
			// Fallback to data field if error field is nil but data exists
			errorMsg = string(obs.Data)
		}
		m.logger.Error("Received 'error' observation from agent", "sandboxID", sandboxID, "actionID", obs.ActionID, "errorData", errorMsg)

		// MODIFIED: Use ExitCode if present, otherwise default to -1 for errors
		exitCode := -1
		if obs.ExitCode != nil {
			exitCode = *obs.ExitCode
		}
		m.sendEndObservation(sandboxID, obs.ActionID, exitCode)

	// Add cases for other types if needed (e.g., 'start', 'stream')
	// Currently, 'start' is sent by InitiateAction, and 'stream' is just broadcast.
	}
	return nil
}

// sendEndObservation constructs and broadcasts an 'end' observation.
func (m *SandboxManager) sendEndObservation(sandboxID, actionID string, exitCode int) {
	if m.hub == nil {
		return
	}

	endData := map[string]interface{}{
		"exit_code": exitCode,
	}

	// Construct the end observation message
	endMsg := map[string]interface{}{
		"observation_type": "end",
		"action_id":        actionID,
		"timestamp":        time.Now().UTC().Format(time.RFC3339Nano),
		"data":             endData,
	}

	endBytes, err := json.Marshal(endMsg)
	if err != nil {
		m.logger.Error("Failed to marshal 'end' observation", "sandboxID", sandboxID, "actionID", actionID, "error", err)
		return
	}

	m.logger.Debug("Pushing observation via Hub", "sandboxID", sandboxID, "actionID", actionID, "type", "end", "size", len(endBytes))
	m.hub.SubmitBroadcast(sandboxID, endBytes)
}

// CreateSpace delegates to SpaceManager.
func (m *SandboxManager) CreateSpace(ctx context.Context, name string, description string, metadata map[string]interface{}) (string, error) {
	return m.spaceManager.CreateSpace(ctx, name, description, metadata)
}

// GetSpace delegates to SpaceManager.
func (m *SandboxManager) GetSpace(ctx context.Context, spaceID string) (*SpaceState, error) {
	return m.spaceManager.GetSpace(ctx, spaceID)
}

// ListSpaces delegates to SpaceManager.
func (m *SandboxManager) ListSpaces(ctx context.Context) ([]*SpaceState, error) {
	return m.spaceManager.ListSpaces(ctx)
}

// UpdateSpace delegates to SpaceManager.
func (m *SandboxManager) UpdateSpace(ctx context.Context, spaceID string, description string, metadata map[string]interface{}) error {
	return m.spaceManager.UpdateSpace(ctx, spaceID, description, metadata)
}

// DeleteSpace deletes a space and all its sandboxes.
func (m *SandboxManager) DeleteSpace(ctx context.Context, spaceID string) error {
	// Get list of sandbox IDs in the space first
	sandboxIDs, err := m.spaceManager.getSpaceSandboxes(spaceID)
	if err != nil {
		if errors.Is(err, ErrSpaceNotFound) {
			return ErrSpaceNotFound // Space doesn't exist
		}
		m.logger.Error("Failed to get sandboxes for space deletion", "spaceID", spaceID, "error", err)
		return fmt.Errorf("failed to get sandboxes for space %s: %w", spaceID, err)
	}

	// Delete all sandboxes associated with the space
	var firstErr error
	for _, sandboxID := range sandboxIDs {
		if delErr := m.DeleteSandbox(ctx, sandboxID); delErr != nil {
			// Log error and store the first one encountered
			m.logger.Error("Failed to delete sandbox while deleting space", "spaceID", spaceID, "sandboxID", sandboxID, "error", delErr)
			if firstErr == nil && !errors.Is(delErr, ErrSandboxNotFound) { // Ignore not found errors during cleanup
				firstErr = delErr
			}
		}
	}

	// After attempting to delete all sandboxes, delete the space entry itself
	if spaceDelErr := m.spaceManager.DeleteSpace(ctx, spaceID); spaceDelErr != nil {
		m.logger.Error("Failed to delete space entry after deleting sandboxes", "spaceID", spaceID, "error", spaceDelErr)
		if firstErr == nil { // Prioritize sandbox deletion errors
			firstErr = spaceDelErr
		}
	}

	if firstErr != nil {
		m.logger.Error("Errors occurred during space deletion", "spaceID", spaceID, "firstError", firstErr)
		return fmt.Errorf("errors occurred deleting space %s: %w", spaceID, firstErr)
	}

	m.logger.Info("Space and associated sandboxes deleted successfully", "spaceID", spaceID)
	return nil
}