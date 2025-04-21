package handler

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"

	"github.com/foreveryh/sandboxai/go/mentisruntime/manager"
	"github.com/foreveryh/sandboxai/go/mentisruntime/ws"
	"github.com/gorilla/mux"
)

type APIHandler struct {
	logger         *slog.Logger
	sandboxManager *manager.SandboxManager
	spaceManager   *manager.SpaceManager
	hub           *ws.Hub
}

func NewAPIHandler(logger *slog.Logger, sandboxManager *manager.SandboxManager, spaceManager *manager.SpaceManager, hub *ws.Hub) *APIHandler {
	return &APIHandler{
		logger:         logger,
		sandboxManager: sandboxManager,
		spaceManager:   spaceManager,
		hub:           hub,
	}
}

// PostShellCommandHandler handles requests to execute a shell command asynchronously.
func (h *APIHandler) PostShellCommandHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"]     // Extract spaceID from path
	sandboxID := vars["sandboxID"] // Corrected key based on route definition

	if spaceID == "" || sandboxID == "" {
		WriteError(w, "Missing spaceID or sandboxID in path", http.StatusBadRequest)
		return
	}

	// --- Validation: Check if sandbox belongs to the space --- 
	sandboxState, getErr := h.sandboxManager.GetSandbox(r.Context(), sandboxID)
	if getErr != nil {
		// If sandbox doesn't exist at all, return 404
		if errors.Is(getErr, manager.ErrSandboxNotFound) || strings.Contains(getErr.Error(), "not found") {
			WriteError(w, fmt.Sprintf("Sandbox %s not found", sandboxID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to get sandbox before initiating action", "spaceID", spaceID, "sandboxID", sandboxID, "error", getErr)
			WriteError(w, "Failed to check sandbox before initiating action: "+getErr.Error(), http.StatusInternalServerError)
		}
		return
	}
	if sandboxState.SpaceID != spaceID {
		h.logger.Warn("Attempt to run shell command on sandbox via incorrect space path", "requestedSpaceID", spaceID, "actualSpaceID", sandboxState.SpaceID, "sandboxID", sandboxID)
		WriteError(w, fmt.Sprintf("Sandbox %s not found in space %s", sandboxID, spaceID), http.StatusNotFound)
		return
	}
	// --- End Validation --- 

	var payload map[string]interface{} // Use map for flexibility
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		WriteError(w, "Invalid request body: "+err.Error(), http.StatusBadRequest) // Use WriteError
		return
	}

	// Basic validation (ensure command exists, etc.) - can be expanded
	if _, ok := payload["command"]; !ok {
		WriteError(w, "Missing 'command' in request body", http.StatusBadRequest) // Use WriteError
		return
	}

	actionID, err := h.sandboxManager.InitiateAction(r.Context(), sandboxID, "shell", payload)
	if err != nil {
		h.logger.Error("Failed to initiate shell action", "sandboxID", sandboxID, "error", err)
		// Map manager errors to appropriate HTTP status codes
		// Example: Check for specific errors like sandbox not found or not running
		if strings.Contains(err.Error(), "not found or not running") { // Basic check, refine with specific errors
			WriteError(w, fmt.Sprintf("Failed to initiate shell command: sandbox %s not found or not running", sandboxID), http.StatusNotFound)
		} else {
			WriteError(w, "Failed to initiate shell command: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted) // 202 Accepted
	json.NewEncoder(w).Encode(map[string]string{"action_id": actionID})
}

// PostIPythonCellHandler handles requests to execute an IPython cell asynchronously.
func (h *APIHandler) PostIPythonCellHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"]     // Extract spaceID from path
	sandboxID := vars["sandboxID"] // Corrected key based on route definition

	if spaceID == "" || sandboxID == "" {
		WriteError(w, "Missing spaceID or sandboxID in path", http.StatusBadRequest)
		return
	}

	// --- Validation: Check if sandbox belongs to the space --- 
	sandboxState, getErr := h.sandboxManager.GetSandbox(r.Context(), sandboxID)
	if getErr != nil {
		// If sandbox doesn't exist at all, return 404
		if errors.Is(getErr, manager.ErrSandboxNotFound) || strings.Contains(getErr.Error(), "not found") {
			WriteError(w, fmt.Sprintf("Sandbox %s not found", sandboxID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to get sandbox before initiating action", "spaceID", spaceID, "sandboxID", sandboxID, "error", getErr)
			WriteError(w, "Failed to check sandbox before initiating action: "+getErr.Error(), http.StatusInternalServerError)
		}
		return
	}
	if sandboxState.SpaceID != spaceID {
		h.logger.Warn("Attempt to run ipython cell on sandbox via incorrect space path", "requestedSpaceID", spaceID, "actualSpaceID", sandboxState.SpaceID, "sandboxID", sandboxID)
		WriteError(w, fmt.Sprintf("Sandbox %s not found in space %s", sandboxID, spaceID), http.StatusNotFound)
		return
	}
	// --- End Validation --- 

	var payload map[string]interface{} // Use map for flexibility
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		WriteError(w, "Invalid request body: "+err.Error(), http.StatusBadRequest) // Use WriteError
		return
	}

	// Basic validation (ensure code exists, etc.) - can be expanded
	if _, ok := payload["code"]; !ok {
		WriteError(w, "Missing 'code' in request body", http.StatusBadRequest) // Use WriteError
		return
	}

	actionID, err := h.sandboxManager.InitiateAction(r.Context(), sandboxID, "ipython", payload)
	if err != nil {
		h.logger.Error("Failed to initiate ipython action", "sandboxID", sandboxID, "error", err)
		// Map manager errors to appropriate HTTP status codes
		// Example: Check for specific errors like sandbox not found or not running
		if strings.Contains(err.Error(), "not found or not running") { // Basic check, refine with specific errors
			WriteError(w, fmt.Sprintf("Failed to initiate IPython cell execution: sandbox %s not found or not running", sandboxID), http.StatusNotFound)
		} else {
			WriteError(w, "Failed to initiate IPython cell execution: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted) // 202 Accepted
	json.NewEncoder(w).Encode(map[string]string{"action_id": actionID})
}

func (h *APIHandler) InternalObservationHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r) // Uses gorilla/mux as per your provided code
	// sandboxID := vars["sandbox_id"] // Correct key for mux
	sandboxID := vars["sandboxID"] // Changed to sandboxID

	if sandboxID == "" {
		// http.Error(w, "Missing sandbox_id in path", http.StatusBadRequest)
		WriteError(w, "Missing sandboxID in path", http.StatusBadRequest) // Use WriteError and updated message
		return
	}

	// Read the raw body
	bodyBytes, err := io.ReadAll(r.Body)
	if err != nil {
		h.logger.Error("Failed to read internal observation body", "sandboxID", sandboxID, "error", err)
		// http.Error(w, "Failed to read request body: "+err.Error(), http.StatusInternalServerError)
		WriteError(w, "Failed to read request body: "+err.Error(), http.StatusInternalServerError) // Use WriteError
		return
	}
	defer r.Body.Close() // Ensure body is closed

	// ******** 添加的日志行 ********
	// Log the raw body received from the agent BEFORE passing it to the manager
	h.logger.Debug("Received raw internal observation body", "sandboxID", sandboxID, "body", string(bodyBytes))
	// ***************************

	// Pass the raw bytes to the manager for processing and broadcasting
	err = h.sandboxManager.ReceiveInternalObservation(sandboxID, bodyBytes)
	if err != nil {
		h.logger.Error("Failed to process internal observation", "sandboxID", sandboxID, "error", err)
		// Determine appropriate error code based on manager error
		// http.Error(w, "Failed to process observation: "+err.Error(), http.StatusInternalServerError)
		WriteError(w, "Failed to process observation: "+err.Error(), http.StatusInternalServerError) // Use WriteError
		return
	}

	// Respond with 200 OK to acknowledge successful receipt and processing attempt.
	// Agent doesn't need to wait for broadcasting.
	w.WriteHeader(http.StatusOK)
}

// ErrorResponse represents an error response
type ErrorResponse struct {
	Message string `json:"message"`
	Detail  string `json:"detail,omitempty"`
}

// WriteError writes an error response in JSON format
func WriteError(w http.ResponseWriter, message string, statusCode int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	json.NewEncoder(w).Encode(ErrorResponse{Message: message})
}

// CreateSandboxRequest represents the request body for creating a sandbox
type CreateSandboxRequest struct {
	SpaceID     string   `json:"space_id"` // Ensure this matches the expected JSON key
	Image       string   `json:"image,omitempty"`
	Command     string   `json:"command,omitempty"` // Keep as string in request
	Metadata    map[string]interface{} `json:"metadata,omitempty"`
}

// CreateSandboxHandler handles requests to create a new sandbox.
func (h *APIHandler) CreateSandboxHandler(w http.ResponseWriter, r *http.Request) {
	var req CreateSandboxRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		WriteError(w, "Invalid request body: "+err.Error(), http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	// Use "default" space if not provided
	if req.SpaceID == "" {
		req.SpaceID = "default"
	}

	// Validate space exists (optional but good practice)
	_, spaceErr := h.spaceManager.GetSpace(r.Context(), req.SpaceID)
	if spaceErr != nil {
		if errors.Is(spaceErr, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", req.SpaceID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to validate space during sandbox creation", "spaceID", req.SpaceID, "error", spaceErr)
			WriteError(w, "Failed to validate space: "+spaceErr.Error(), http.StatusInternalServerError)
		}
		return
	}

	h.logger.Info("Received request to create sandbox", "spaceID", req.SpaceID, "image", req.Image, "command", req.Command)

	// Prepare command as a slice
	var commandSlice []string
	if req.Command != "" {
		// Simple case: treat the whole string as the command/entrypoint
		commandSlice = []string{req.Command}
		// Alternative (if splitting by space is desired):
		// commandSlice = strings.Fields(req.Command)
	}


	// Call manager to create sandbox, passing command as a slice
	// sandboxID, err := h.sandboxManager.CreateSandbox(r.Context(), req.SpaceID, req.Image, req.Command)
	sandboxID, err := h.sandboxManager.CreateSandbox(r.Context(), req.SpaceID, req.Image, commandSlice) // Pass slice
	if err != nil {
		h.logger.Error("Failed to create sandbox", "spaceID", req.SpaceID, "image", req.Image, "command", req.Command, "error", err)
		// Map manager errors to HTTP status codes
		if errors.Is(err, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", req.SpaceID), http.StatusNotFound)
		} else {
			// Provide more context in the error message
			WriteError(w, fmt.Sprintf("Failed to create sandbox: %v", err), http.StatusInternalServerError)
		}
		return
	}

	// Retrieve the created sandbox state to include in the response
	sandboxState, getErr := h.sandboxManager.GetSandbox(r.Context(), sandboxID)
	if getErr != nil {
		// This shouldn't happen right after creation, but handle defensively
		h.logger.Error("Failed to retrieve sandbox state immediately after creation", "sandboxID", sandboxID, "error", getErr)
		// Return 201 Created but with a warning or minimal body
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(map[string]string{
			"sandbox_id": sandboxID,
			"warning":    "Sandbox created, but failed to retrieve its full state.",
		})
		return
	}


	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated) // 201 Created
	// Return the full sandbox state in the response
	json.NewEncoder(w).Encode(sandboxState)
}

// GetSandboxHandler handles requests to retrieve a specific sandbox.
func (h *APIHandler) GetSandboxHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"]     // Use mux.Vars
	sandboxID := vars["sandboxID"] // Use mux.Vars

	if spaceID == "" || sandboxID == "" {
		WriteError(w, "Missing spaceID or sandboxID in path", http.StatusBadRequest)
		return
	}

	// First, check if the space exists (optional but good practice)
	_, err := h.spaceManager.GetSpace(r.Context(), spaceID)
	if err != nil {
		if errors.Is(err, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", spaceID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to get space during sandbox retrieval", "spaceID", spaceID, "error", err)
			WriteError(w, "Failed to check space existence: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	// Get the sandbox state from the manager
	sandboxState, err := h.sandboxManager.GetSandbox(r.Context(), sandboxID)
	if err != nil {
		// Check if the error indicates the sandbox wasn't found
		// Assuming GetSandbox returns an error containing "not found" for that case.
		// TODO: Refine manager.GetSandbox to return a specific error like ErrSandboxNotFound
		if errors.Is(err, manager.ErrSandboxNotFound) { // Use ErrSandboxNotFound if defined in manager
			WriteError(w, fmt.Sprintf("Sandbox %s not found in space %s", sandboxID, spaceID), http.StatusNotFound)
		} else if strings.Contains(err.Error(), "not found") { // Fallback check
			WriteError(w, fmt.Sprintf("Sandbox %s not found in space %s", sandboxID, spaceID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to get sandbox", "spaceID", spaceID, "sandboxID", sandboxID, "error", err)
			WriteError(w, "Failed to retrieve sandbox: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	// Check if the retrieved sandbox actually belongs to the requested space
	if sandboxState.SpaceID != spaceID {
		h.logger.Warn("Sandbox found but belongs to different space", "requestedSpaceID", spaceID, "actualSpaceID", sandboxState.SpaceID, "sandboxID", sandboxID)
		WriteError(w, fmt.Sprintf("Sandbox %s not found in space %s", sandboxID, spaceID), http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	// Encode the SandboxState (or a subset/transformed version if needed)
	json.NewEncoder(w).Encode(sandboxState)
}

// DeleteSandboxHandler handles requests to delete an existing sandbox.
func (h *APIHandler) DeleteSandboxHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"]     // Use mux.Vars
	sandboxID := vars["sandboxID"] // Use mux.Vars

	if spaceID == "" || sandboxID == "" {
		WriteError(w, "Missing spaceID or sandboxID in path", http.StatusBadRequest)
		return
	}

	// Optional: Check if space exists first (consistency)
	_, spaceErr := h.spaceManager.GetSpace(r.Context(), spaceID)
	if spaceErr != nil {
		if errors.Is(spaceErr, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", spaceID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to get space during sandbox deletion", "spaceID", spaceID, "error", spaceErr)
			WriteError(w, "Failed to check space existence: "+spaceErr.Error(), http.StatusInternalServerError)
		}
		return
	}

	// Optional: Get sandbox first to verify it belongs to the space before deleting
	// This adds an extra check but prevents deleting a sandbox via the wrong space path.
	sandboxState, getErr := h.sandboxManager.GetSandbox(r.Context(), sandboxID)
	if getErr != nil {
		// If sandbox doesn't exist at all, return 404
		if errors.Is(getErr, manager.ErrSandboxNotFound) || strings.Contains(getErr.Error(), "not found") {
			WriteError(w, fmt.Sprintf("Sandbox %s not found", sandboxID), http.StatusNotFound)
		} else {
			h.logger.Error("Failed to get sandbox before deletion", "spaceID", spaceID, "sandboxID", sandboxID, "error", getErr)
			WriteError(w, "Failed to check sandbox before deletion: "+getErr.Error(), http.StatusInternalServerError)
		}
		return
	}
	if sandboxState.SpaceID != spaceID {
		h.logger.Warn("Attempt to delete sandbox via incorrect space path", "requestedSpaceID", spaceID, "actualSpaceID", sandboxState.SpaceID, "sandboxID", sandboxID)
		WriteError(w, fmt.Sprintf("Sandbox %s not found in space %s", sandboxID, spaceID), http.StatusNotFound)
		return
	}

	// Proceed with deletion
	err := h.sandboxManager.DeleteSandbox(r.Context(), sandboxID)
	if err != nil {
		h.logger.Error("Failed to delete sandbox", "spaceID", spaceID, "sandboxID", sandboxID, "error", err)
		// Check if the error indicates the sandbox wasn't found (might be redundant due to check above, but safe)
		// TODO: Refine manager.DeleteSandbox to return a specific ErrSandboxNotFound
		if errors.Is(err, manager.ErrSandboxNotFound) { // Use ErrSandboxNotFound if defined in manager
			WriteError(w, fmt.Sprintf("Sandbox %s not found", sandboxID), http.StatusNotFound)
		} else if strings.Contains(err.Error(), "not found") { // Fallback check
			WriteError(w, fmt.Sprintf("Sandbox %s not found", sandboxID), http.StatusNotFound)
		} else {
			WriteError(w, "Failed to delete sandbox: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.WriteHeader(http.StatusNoContent) // 204 No Content for successful deletion
}

// HealthCheckHandler responds with a simple OK status.
func HealthCheckHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

// CreateSpaceHandler handles requests to create a new space.
func (h *APIHandler) CreateSpaceHandler(w http.ResponseWriter, r *http.Request) {
	var payload struct {
		Name        string                 `json:"name"`
		Description string                 `json:"description,omitempty"`
		Metadata    map[string]interface{} `json:"metadata,omitempty"`
	}

	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		WriteError(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if payload.Name == "" {
		WriteError(w, "Name is required", http.StatusBadRequest)
		return
	}

	spaceID, err := h.spaceManager.CreateSpace(r.Context(), payload.Name, payload.Description, payload.Metadata)
	if err != nil {
		h.logger.Error("Failed to create space", "error", err)
		// Check if the error indicates a duplicate name
		// Use a simple string check for now, ideally SpaceManager returns a specific error type
		if errors.Is(err, manager.ErrSpaceNameConflict) { // Assuming ErrSpaceNameConflict exists
			WriteError(w, "Failed to create space: "+err.Error(), http.StatusConflict) // Return 409 Conflict
		} else {
			WriteError(w, "Failed to create space: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	// Return the created space details
	json.NewEncoder(w).Encode(map[string]interface{}{
		"space_id":    spaceID,
		"name":        payload.Name,
		"description": payload.Description,
		"metadata":    payload.Metadata,
	})
}

// GetSpaceHandler handles requests to get a space by ID.
func (h *APIHandler) GetSpaceHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"] // Use mux.Vars
	if spaceID == "" {
		WriteError(w, "Missing spaceID in path", http.StatusBadRequest) // Use WriteError for consistency
		return
	}

	space, err := h.spaceManager.GetSpace(r.Context(), spaceID)
	if err != nil {
		if errors.Is(err, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", spaceID), http.StatusNotFound) // Use WriteError
			return
		}
		h.logger.Error("Failed to get space", "spaceID", spaceID, "error", err)
		WriteError(w, fmt.Sprintf("Failed to get space: %v", err), http.StatusInternalServerError) // Use WriteError
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(space)
}

// ListSpacesHandler handles requests to list all spaces.
func (h *APIHandler) ListSpacesHandler(w http.ResponseWriter, r *http.Request) {
	spaces, err := h.spaceManager.ListSpaces(r.Context())
	if err != nil {
		h.logger.Error("Failed to list spaces", "error", err)
		WriteError(w, "Failed to list spaces: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(spaces)
}

// UpdateSpaceHandler handles requests to update a space.
func (h *APIHandler) UpdateSpaceHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"] // Use mux.Vars
	if spaceID == "" {
		WriteError(w, "Missing spaceID in path", http.StatusBadRequest)
		return
	}

	var payload struct {
		Description string                 `json:"description,omitempty"`
		Metadata    map[string]interface{} `json:"metadata,omitempty"`
	}

	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		WriteError(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if err := h.spaceManager.UpdateSpace(r.Context(), spaceID, payload.Description, payload.Metadata); err != nil {
		h.logger.Error("Failed to update space", "spaceID", spaceID, "error", err)
		if errors.Is(err, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", spaceID), http.StatusNotFound)
		} else {
			WriteError(w, "Failed to update space: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

// DeleteSpaceHandler handles requests to delete a space and its sandboxes.
func (h *APIHandler) DeleteSpaceHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	spaceID := vars["spaceID"] // Use mux.Vars
	if spaceID == "" {
		WriteError(w, "Missing spaceID in path", http.StatusBadRequest)
		return
	}

	err := h.spaceManager.DeleteSpace(r.Context(), spaceID)
	if err != nil {
		h.logger.Error("Failed to delete space", "spaceID", spaceID, "error", err)
		if errors.Is(err, manager.ErrSpaceNotFound) {
			WriteError(w, fmt.Sprintf("Space %s not found", spaceID), http.StatusNotFound)
		} else {
			WriteError(w, "Failed to delete space: "+err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.WriteHeader(http.StatusNoContent) // 204 No Content for successful deletion
}