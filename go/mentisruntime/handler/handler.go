package handler

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"

	"github.com/gorilla/mux"

	"github.com/foreveryh/sandboxai/go/mentisruntime/manager" // Corrected manager package path
	"github.com/foreveryh/sandboxai/go/mentisruntime/ws"      // Corrected ws package path
)

type APIHandler struct {
	logger  *slog.Logger
	manager *manager.SandboxManager // Inject SandboxManager
	hub     *ws.Hub                 // Inject Hub
	// Add other dependencies like Docker client if needed for other handlers
}

func NewAPIHandler(logger *slog.Logger, manager *manager.SandboxManager, hub *ws.Hub) *APIHandler {
	return &APIHandler{
		logger:  logger,
		manager: manager,
		hub:     hub, // Store hub
	}
}

// PostShellCommandHandler handles requests to execute a shell command asynchronously.
func (h *APIHandler) PostShellCommandHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	sandboxID := vars["sandbox_id"]

	var payload map[string]interface{} // Use map for flexibility
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "Invalid request body: "+err.Error(), http.StatusBadRequest)
		return
	}

	// Basic validation (ensure command exists, etc.) - can be expanded
	if _, ok := payload["command"]; !ok {
		http.Error(w, "Missing 'command' in request body", http.StatusBadRequest)
		return
	}

	actionID, err := h.manager.InitiateAction(r.Context(), sandboxID, "shell", payload)
	if err != nil {
		h.logger.Error("Failed to initiate shell action", "sandboxID", sandboxID, "error", err)
		// Map manager errors to appropriate HTTP status codes
		// For now, using 500 for simplicity
		http.Error(w, "Failed to initiate shell command: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted) // 202 Accepted
	json.NewEncoder(w).Encode(map[string]string{"action_id": actionID})
}

// PostIPythonCellHandler handles requests to execute an IPython cell asynchronously.
func (h *APIHandler) PostIPythonCellHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	sandboxID := vars["sandbox_id"]

	var payload map[string]interface{} // Use map for flexibility
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "Invalid request body: "+err.Error(), http.StatusBadRequest)
		return
	}

	// Basic validation (ensure code exists, etc.) - can be expanded
	if _, ok := payload["code"]; !ok {
		http.Error(w, "Missing 'code' in request body", http.StatusBadRequest)
		return
	}

	actionID, err := h.manager.InitiateAction(r.Context(), sandboxID, "ipython", payload)
	if err != nil {
		h.logger.Error("Failed to initiate ipython action", "sandboxID", sandboxID, "error", err)
		// Map manager errors to appropriate HTTP status codes
		http.Error(w, "Failed to initiate IPython cell execution: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted) // 202 Accepted
	json.NewEncoder(w).Encode(map[string]string{"action_id": actionID})
}

// InternalObservationHandler handles observation posts from the agent inside the sandbox.
func (h *APIHandler) InternalObservationHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	sandboxID := vars["sandbox_id"]

	if sandboxID == "" {
		http.Error(w, "Missing sandbox_id in path", http.StatusBadRequest)
		return
	}

	bodyBytes, err := io.ReadAll(r.Body)
	if err != nil {
		h.logger.Error("Failed to read internal observation body", "sandboxID", sandboxID, "error", err)
		http.Error(w, "Failed to read request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	// Pass the raw bytes to the manager/hub for processing and broadcasting
	// The manager or hub will be responsible for potentially unmarshalling
	// if needed, or just broadcasting the raw message.
	err = h.manager.ReceiveInternalObservation(sandboxID, bodyBytes)
	if err != nil {
		h.logger.Error("Failed to process internal observation", "sandboxID", sandboxID, "error", err)
		// Determine appropriate error code based on manager error
		http.Error(w, "Failed to process observation: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK) // 200 OK for successful receipt
}

// CreateSandboxHandler handles requests to create a new sandbox.
func (h *APIHandler) CreateSandboxHandler(w http.ResponseWriter, r *http.Request) {
	// TODO: Add request body parsing if options are needed for creation

	sandboxID, err := h.manager.CreateSandbox(r.Context() /* pass options if any */)
	if err != nil {
		h.logger.Error("Failed to create sandbox", "error", err)
		// Map manager errors to appropriate HTTP status codes
		// Example: Check for specific error types if needed
		http.Error(w, "Failed to create sandbox: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated) // 201 Created
	json.NewEncoder(w).Encode(map[string]string{"sandbox_id": sandboxID})
}

// DeleteSandboxHandler handles requests to delete an existing sandbox.
func (h *APIHandler) DeleteSandboxHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	sandboxID := vars["sandbox_id"]

	if sandboxID == "" {
		http.Error(w, "Missing sandbox_id in path", http.StatusBadRequest)
		return
	}

	err := h.manager.DeleteSandbox(r.Context(), sandboxID)
	if err != nil {
		h.logger.Error("Failed to delete sandbox", "sandboxID", sandboxID, "error", err)
		// Map manager errors to appropriate HTTP status codes
		// Example: Check if error means 'not found' -> 404
		// if errors.Is(err, manager.ErrSandboxNotFound) { // Assuming manager defines such an error
		// 	http.Error(w, err.Error(), http.StatusNotFound)
		// 	return
		// }
		http.Error(w, "Failed to delete sandbox: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent) // 204 No Content
}

// TODO: Add handlers for CreateSandbox, DeleteSandbox etc.
// These might interact directly with the manager or a Docker client wrapper.
