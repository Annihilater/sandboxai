package ws

import (
	"log/slog"
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
		broadcast:            make(chan *BroadcastMessage),
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