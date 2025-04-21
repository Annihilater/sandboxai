package ws

import (
	"log/slog"
	"strings"
	"sync"
)

// Hub maintains the set of active clients and broadcasts messages to the
// clients associated with specific sandboxes.
type Hub struct {
	// Registered clients.
	clients map[*Client]bool

	// Inbound messages from the manager to be broadcast.
	// The key of the outer map is the sandbox ID.
	// The value is the message payload to send.
	broadcast chan *BroadcastMessage

	// Register requests from the clients.
	register chan *Client

	// Unregister requests from clients.
	unregister chan *Client

	// Map of sandbox IDs to the set of clients subscribed to that sandbox.
	sandboxSubscriptions map[string]map[*Client]bool

	// Mutex to protect sandboxSubscriptions
	mu sync.RWMutex

	logger *slog.Logger
}

// BroadcastMessage encapsulates a message intended for a specific sandbox.
type BroadcastMessage struct {
	SandboxID string
	Message   []byte
}

func NewHub(logger *slog.Logger) *Hub {
	return &Hub{
		// Increase buffer size, e.g., to 256 (adjust if needed)
		broadcast:            make(chan *BroadcastMessage, 256), // <--- 修改这里
		register:             make(chan *Client),
		unregister:           make(chan *Client),
		clients:              make(map[*Client]bool),
		sandboxSubscriptions: make(map[string]map[*Client]bool),
		logger:               logger.With("component", "websocket-hub"),
	}
}

func (h *Hub) Run() {
	h.logger.Info("WebSocket Hub started")
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			if _, ok := h.sandboxSubscriptions[client.sandboxID]; !ok {
				h.sandboxSubscriptions[client.sandboxID] = make(map[*Client]bool)
			}
			h.sandboxSubscriptions[client.sandboxID][client] = true
			h.mu.Unlock()
			h.logger.Debug("Client registered", "sandboxID", client.sandboxID, "remoteAddr", client.conn.RemoteAddr().String())

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send) // Close the send channel when unregistering
				if subs, ok := h.sandboxSubscriptions[client.sandboxID]; ok {
					delete(subs, client)
					if len(subs) == 0 {
						delete(h.sandboxSubscriptions, client.sandboxID)
					}
				}
				h.logger.Debug("Client unregistered", "sandboxID", client.sandboxID, "remoteAddr", client.conn.RemoteAddr().String())
			}
			h.mu.Unlock()

		case broadcastMsg := <-h.broadcast:
			h.mu.RLock()
			subscribers, ok := h.sandboxSubscriptions[broadcastMsg.SandboxID]
			if ok {
				h.logger.Debug("Broadcasting message", "sandboxID", broadcastMsg.SandboxID, "numSubscribers", len(subscribers), "messageSize", len(broadcastMsg.Message))
				for client := range subscribers {
					select {
					case client.send <- broadcastMsg.Message:
					default:
						// Prevent blocking if the client's send buffer is full
						h.logger.Warn("Client send channel full, closing client", "sandboxID", client.sandboxID, "remoteAddr", client.conn.RemoteAddr().String())
						// Closing the client here might be too aggressive, consider alternative strategies
						// For now, we'll rely on the writePump detecting the closed channel
						// close(client.send)
						// delete(h.clients, client)
						// delete(subscribers, client)
					}
				}
			} else {
				h.logger.Debug("No subscribers for sandbox, discarding message", "sandboxID", broadcastMsg.SandboxID)
			}
			h.mu.RUnlock()
		}
	}
}

// SubmitBroadcast sends a message to the hub for broadcasting to relevant clients.
// This method is intended to be called by the SandboxManager or other components.
func (h *Hub) SubmitBroadcast(sandboxID string, message []byte) {
	broadcastMsg := &BroadcastMessage{
		SandboxID: sandboxID,
		Message:   message,
	}
	select {
	case h.broadcast <- broadcastMsg:
		h.logger.Debug("Submitted message to broadcast channel", "sandboxID", sandboxID, "messageSize", len(message))
	default:
		// Hub's broadcast channel is full, might indicate a bottleneck or dead hub.
		h.logger.Error("Hub broadcast channel full, discarding message", "sandboxID", sandboxID)
	}
}

// BroadcastToSandbox sends a message to all clients connected for a specific sandbox.
func (h *Hub) BroadcastToSandbox(sandboxID string, message []byte) {
	h.mu.RLock()
	subscribers, ok := h.sandboxSubscriptions[sandboxID]
	h.mu.RUnlock()

	if !ok || len(subscribers) == 0 {
		h.logger.Debug("No subscribers for sandbox, discarding message", "sandboxID", sandboxID)
		return
	}

	// *** ADDED DIAGNOSTIC LOGGING ***
	clientAddrs := []string{}
	h.mu.RLock()
	for client := range subscribers {
		clientAddrs = append(clientAddrs, client.conn.RemoteAddr().String())
	}
	h.mu.RUnlock()
	h.logger.Debug("Broadcasting message details",
		"sandboxID", sandboxID,
		"numSubscribers", len(subscribers),
		"subscriberAddrs", strings.Join(clientAddrs, ", "), // Log addresses
		"messageContent", string(message))                   // Log content being sent
	// *** END ADDED DIAGNOSTIC LOGGING ***

	// Use a temporary map to avoid holding the lock while sending
	clientsToSend := make(map[*Client]bool)
	h.mu.RLock()
	for client := range subscribers {
		clientsToSend[client] = true
	}
	h.mu.RUnlock()

	for client := range clientsToSend {
		// *** ADDED DIAGNOSTIC LOGGING ***
		h.logger.Debug("Attempting to send to client", "clientAddr", client.conn.RemoteAddr().String())
		// *** END ADDED DIAGNOSTIC LOGGING ***
		select {
		case client.send <- message:
			// *** ADDED DIAGNOSTIC LOGGING ***
			h.logger.Debug("Successfully submitted to client channel", "clientAddr", client.conn.RemoteAddr().String())
			// *** END ADDED DIAGNOSTIC LOGGING ***
		default:
			// If the send channel is full, assume the client is slow or disconnected.
			// Close the client connection and remove it.
			h.logger.Warn("Client send channel full, closing connection", "sandboxID", sandboxID, "clientAddr", client.conn.RemoteAddr().String())
			// Need to run unregister in a goroutine or handle locking carefully
			// to avoid deadlock if unregister tries to lock the hub.
			go func(c *Client) {
				h.unregister <- c // Send to unregister channel
				// close(c.send) // Closing channel here might cause panic if writePump tries to read after close
			}(client)
		}
	}
}