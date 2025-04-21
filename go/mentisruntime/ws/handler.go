package ws

import (
	"log/slog"
	"net/http"

	"github.com/gorilla/mux"
	// No longer import manager directly
	// "github.com/foreveryh/sandboxai/go/mentisruntime/manager"
)

// ServeWs handles websocket requests from the peer.
// It upgrades the HTTP connection, creates a client, registers it with the hub,
// and starts the read/write pumps.
// It now accepts a SandboxChecker interface instead of a concrete manager.
func ServeWs(hub *Hub, checker SandboxChecker, w http.ResponseWriter, r *http.Request, logger *slog.Logger) {
	vars := mux.Vars(r)
	sandboxID, ok := vars["sandboxID"]
	if !ok {
		logger.Error("Missing sandboxID in WebSocket path")
		http.Error(w, "Missing sandboxID", http.StatusBadRequest)
		return
	}

	// Validate if the sandbox exists using the checker interface
	exists, err := checker.SandboxExists(r.Context(), sandboxID)
	if err != nil {
		logger.Error("Failed to check sandbox existence", "error", err, "sandboxID", sandboxID)
		http.Error(w, "Internal server error", http.StatusInternalServerError)
		return
	}
	if !exists {
		logger.Warn("Attempted WebSocket connection to non-existent sandbox", "sandboxID", sandboxID)
		http.Error(w, "Sandbox not found", http.StatusNotFound)
		return
	}

	conn, err := upgrader.Upgrade(w, r, nil) // upgrader is defined in client.go
	if err != nil {
		logger.Error("Failed to upgrade WebSocket connection", "error", err, "sandboxID", sandboxID)
		// Upgrade automatically sends an error response, so no need for http.Error here.
		return
	}

	clientLogger := logger.With("component", "websocket-client", "sandboxID", sandboxID, "remoteAddr", conn.RemoteAddr().String())
	client := &Client{
		hub:       hub,
		conn:      conn,
		send:      make(chan []byte, 256), // Buffered channel
		sandboxID: sandboxID,
		logger:    clientLogger,
	}

	client.logger.Info("WebSocket client connection established")

	// Allow registration of the client to the hub.
	client.hub.register <- client

	// Allow collection of memory referenced by the caller by doing all work in
	// new goroutines.
	go client.writePump()
	go client.readPump()
}