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
	"strings"
	"sync"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image"
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
	ContainerID string
	AgentURL    string // e.g., http://<container_ip>:<agent_port>
	IsRunning   bool
	SpaceID     string // Reference to the space this sandbox belongs to
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
	ObservationType string      `json:"observation_type"` 
	ActionID        string      `json:"action_id"`
	Timestamp       string      `json:"timestamp"`
	Data            interface{} `json:"data,omitempty"`
}

type StartObservationData struct {
	// Add relevant start data if needed
}

type StreamObservationData struct {
	Stream string `json:"stream"` // "stdout" or "stderr"
	Line   string `json:"line"`
}

type ErrorObservationData struct {
	Error string `json:"error"`
}

type EndObservationData struct {
	ExitCode int    `json:"exit_code"`
	Error    string `json:"error,omitempty"` // Error message if exit code != 0
}

// AgentObservation defines the structure expected from the agent's streaming response lines.
// This allows the manager to understand structured messages like results.
type AgentObservation struct {
	Type     string          `json:"type"` // e.g., "stream", "result"
	Stream   string          `json:"stream,omitempty"` // "stdout", "stderr"
	Line     string          `json:"line,omitempty"`
	ExitCode *int            `json:"exit_code,omitempty"` // Use pointer to distinguish 0 from unset
	Error    string          `json:"error,omitempty"`
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

	agentPort := "8000/tcp" // Default agent port inside the container

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
		out, err := m.dockerClient.ImagePull(pullCtx, imageName, image.PullOptions{}) // Change types.ImagePullOptions to image.PullOptions
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
			ExposedPorts: nat.PortSet{nat.Port(agentPort): struct{}{}}, // Expose agent port
			Cmd:          command, // Use the command parameter
		},
		&container.HostConfig{
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

	// 4. Inspect the container to get its IP address on the default bridge network
	// Use a new context for this inspection
	inspectStartCtx, inspectStartCancel := context.WithTimeout(ctx, 10*time.Second)
	defer inspectStartCancel()
	inspectData, err := m.dockerClient.ContainerInspect(inspectStartCtx, resp.ID)
	if err != nil {
		m.logger.Error("Failed to inspect container after start", "sandboxID", sandboxID, "containerID", resp.ID, "error", err)
		// Consider stopping and removing the container here as well
		return "", fmt.Errorf("failed to inspect container %s: %w", resp.ID, err)
	}

	// Find IP address - assumes default bridge network
	var containerIP string
	if inspectData.NetworkSettings != nil && inspectData.NetworkSettings.Networks != nil {
		// Prefer non-default bridge network if available (more robust)
		for name, netSettings := range inspectData.NetworkSettings.Networks {
			if name != "bridge" && netSettings.IPAddress != "" {
				containerIP = netSettings.IPAddress
				m.logger.Debug("Found container IP on non-default network", "network", name, "ip", containerIP)
				break
			}
		}
		// Fallback to bridge network if no other IP found
		if containerIP == "" {
			if bridgeSettings, ok := inspectData.NetworkSettings.Networks["bridge"]; ok && bridgeSettings.IPAddress != "" {
				containerIP = bridgeSettings.IPAddress
				m.logger.Debug("Found container IP on default bridge network", "ip", containerIP)
			}
		}
		// Fallback to the first available IP if still not found (less ideal)
		if containerIP == "" {
			for name, netSettings := range inspectData.NetworkSettings.Networks {
				if netSettings.IPAddress != "" {
					containerIP = netSettings.IPAddress
					m.logger.Warn("Falling back to first available container IP", "network", name, "ip", containerIP)
					break
				}
			}
		}
	}

	if containerIP == "" {
		m.logger.Error("Failed to find container IP address", "sandboxID", sandboxID, "containerID", resp.ID, "networks", inspectData.NetworkSettings.Networks)
		// Consider stopping and removing the container
		rmCtx, rmCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer rmCancel()
		_ = m.dockerClient.ContainerRemove(rmCtx, resp.ID, container.RemoveOptions{Force: true})
		return "", fmt.Errorf("failed to find IP address for container %s", resp.ID)
	}

	// 5. Construct Agent URL
	portNum := strings.Split(agentPort, "/")[0]
	agentURL := fmt.Sprintf("http://%s:%s", containerIP, portNum)

	// Create sandbox state
	state := &SandboxState{
		ContainerID: resp.ID,
		AgentURL:    agentURL,
		IsRunning:   true,
		SpaceID:     spaceID, // Save the space ID
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

	// Always broadcast the raw data first to ensure clients receive it
	// regardless of parsing success or failure
	if m.hub != nil {
		m.logger.Debug("Broadcasting raw observation data", "sandboxID", sandboxID)
		m.hub.SubmitBroadcast(sandboxID, observationBytes)
	}

	// Attempt to parse the incoming observation data
	var obs Observation
	if err := json.Unmarshal(observationBytes, &obs); err != nil {
		m.logger.Error("Failed to unmarshal internal observation from agent", "error", err, "sandboxID", sandboxID, "rawData", string(observationBytes))
		// Don't return error to agent, just log it and continue
		return nil
	}
	// ***** 添加这个日志块 *****
	m.logger.Debug("Parsed internal observation struct",
		"sandboxID", sandboxID,
		"parsedActionID", obs.ActionID,
		"parsedObservationType", obs.ObservationType,
		"parsedTimestamp", obs.Timestamp,
		// "parsedData", obs.Data, // 暂时注释掉Data，避免可能的复杂对象打印问题
		"rawData", string(observationBytes)) // 再次打印原始数据以便对比
	// **************************
	// Log the received observation
	m.logger.Debug("Received internal observation", "sandboxID", sandboxID, "actionID", obs.ActionID, "type", obs.ObservationType)

	// Ensure actionID is present
	if obs.ActionID == "" {
		m.logger.Error("Received internal observation without action_id", "sandboxID", sandboxID, "type", obs.ObservationType, "rawData", string(observationBytes))
		// Cannot process further without actionID
		return nil // Ignore observation without actionID
	}

	// Broadcast the received observation via WebSocket hub
	if m.hub != nil {
		// Re-marshal the parsed object to ensure consistent format? Or send raw? Send raw for now.
		m.hub.SubmitBroadcast(sandboxID, observationBytes)
	}

	// Handle both 'result' and 'end' observation types to ensure proper completion
	if obs.ObservationType == "result" || obs.ObservationType == "end" {
		m.logger.Info(fmt.Sprintf("Received '%s' observation, sending 'end'", obs.ObservationType), "sandboxID", sandboxID, "actionID", obs.ActionID)

		// Extract exit code and error from the result data
		var exitCode int = 0 // Default to success if parsing fails
		var errorMsg string
		
		// Attempt to parse the Data field based on expected structure
		if dataMap, ok := obs.Data.(map[string]interface{}); ok {
			if ec, ok := dataMap["exit_code"].(float64); ok { // JSON numbers are float64
				exitCode = int(ec)
			} else if ec, ok := dataMap["exit_code"].(int); ok { // Handle direct int case
				exitCode = ec
			} else {
				m.logger.Warn("Could not parse 'exit_code' from data", "actionID", obs.ActionID, "data", obs.Data)
			}
			if errMsg, ok := dataMap["error"].(string); ok {
				errorMsg = errMsg
			}
		} else {
			m.logger.Warn("Received observation with unexpected data format", "actionID", obs.ActionID, "type", obs.ObservationType, "data", obs.Data)
		}

		// Always send the 'end' observation to ensure client knows the action is complete
		m.pushObservation(sandboxID, obs.ActionID, "end", EndObservationData{ExitCode: exitCode, Error: errorMsg})
	}

	return nil
}

// --- Space Management Methods (Delegated to SpaceManager) ---

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