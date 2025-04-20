package hub

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const (
	// Time allowed to write a message to the peer.
	writeWait = 10 * time.Second

	// Time allowed to read the next pong message from the peer.
	pongWait = 60 * time.Second

	// Send pings to peer with this period. Must be less than pongWait.
	pingPeriod = (pongWait * 9) / 10

	// Maximum message size allowed from peer.
	maxMessageSize = 512
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	// Allow all origins for development, consider restricting in production
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// Client represents a single WebSocket client connection.
type Client struct {
	sandboxID string
	hub       *Hub
	conn      *websocket.Conn
	send      chan []byte // Buffered channel of outbound messages.
}

// Hub maintains the set of active clients and broadcasts messages.
type Hub struct {
	// Registered clients. Maps sandboxID to a map of clients connected to that sandbox.
	clients map[string]map[*Client]bool

	// Inbound messages from the clients (optional, if bidirectional needed).
	// broadcast chan []byte

	// Register requests from the clients.
	register chan *Client

	// Unregister requests from clients.
	unregister chan *Client

	logger *slog.Logger
	mu     sync.RWMutex // Protects the clients map
}

// NewHub creates a new Hub instance.
func NewHub(logger *slog.Logger) *Hub {
	return &Hub{
		// broadcast:  make(chan []byte),
		register:   make(chan *Client),
		unregister: make(chan *Client),
		clients:    make(map[string]map[*Client]bool),
		logger:     logger,
	}
}

// Run starts the Hub's event loop.
func (h *Hub) Run() {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			if _, ok := h.clients[client.sandboxID]; !ok {
				h.clients[client.sandboxID] = make(map[*Client]bool)
			}
			h.clients[client.sandboxID][client] = true
			h.mu.Unlock()
			h.logger.Info("Client registered", "sandboxID", client.sandboxID, "remoteAddr", client.conn.RemoteAddr())

		case client := <-h.unregister:
			h.mu.Lock()
			if clientsForSandbox, ok := h.clients[client.sandboxID]; ok {
				if _, ok := clientsForSandbox[client]; ok {
					delete(clientsForSandbox, client)
					close(client.send)
					if len(clientsForSandbox) == 0 {
						delete(h.clients, client.sandboxID)
					}
					h.logger.Info("Client unregistered", "sandboxID", client.sandboxID, "remoteAddr", client.conn.RemoteAddr())
				}
			}
			h.mu.Unlock()

			// case message := <-h.broadcast: // Optional: If hub needs to broadcast generic messages
			// 	h.mu.RLock()
			// 	for _, clientsForSandbox := range h.clients {
			// 		for client := range clientsForSandbox {
			// 			select {
			// 			case client.send <- message:
			// 			default:
			// 				close(client.send)
			// 				delete(clientsForSandbox, client) // Consider moving unregister logic here
			// 			}
			// 		}
			// 	}
			// 	h.mu.RUnlock()
		}
	}
}

// BroadcastToSandbox sends a message to all clients connected to a specific sandbox.
func (h *Hub) BroadcastToSandbox(sandboxID string, message interface{}) {
	messageBytes, err := json.Marshal(message)
	if err != nil {
		h.logger.Error("Failed to marshal message for broadcast", "error", err, "sandboxID", sandboxID)
		return
	}

	h.mu.RLock()
	clientsForSandbox, ok := h.clients[sandboxID]
	if ok {
		for client := range clientsForSandbox {
			select {
			case client.send <- messageBytes:
			default:
				// Log or handle the case where the send channel is full/closed
				h.logger.Warn("Failed to send message to client, channel likely full or closed", "sandboxID", sandboxID, "remoteAddr", client.conn.RemoteAddr())
				// Optionally unregister the client here if the channel is closed
				// close(client.send)
				// delete(clientsForSandbox, client)
			}
		}
	}
	h.mu.RUnlock()
}

// writePump pumps messages from the hub to the WebSocket connection.
func (c *Client) writePump() {
	defer func() {
		c.conn.Close()
	}()
	for {
		message, ok := <-c.send
		if !ok {
			// The hub closed the channel.
			c.conn.WriteMessage(websocket.CloseMessage, []byte{})
			return
		}

		w, err := c.conn.NextWriter(websocket.TextMessage)
		if err != nil {
			return
		}
		w.Write(message)

		if err := w.Close(); err != nil {
			return
		}
	}
}

// readPump pumps messages from the WebSocket connection to the hub (optional).
// Currently, it just handles pong messages and unregisters on error.
func (c *Client) readPump() {
	defer func() {
		c.hub.unregister <- c
		c.conn.Close()
	}()
	// Set read limits, pong handlers etc. if needed
	// c.conn.SetReadLimit(maxMessageSize)
	// c.conn.SetReadDeadline(time.Now().Add(pongWait))
	// c.conn.SetPongHandler(func(string) error { c.conn.SetReadDeadline(time.Now().Add(pongWait)); return nil })
	for {
		_, _, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				c.hub.logger.Warn("WebSocket unexpected close error", "error", err, "remoteAddr", c.conn.RemoteAddr())
			}
			break
		}
		// Messages read are currently ignored, as we only push observations
	}
}

// ServeWs handles WebSocket requests from the peer.
func ServeWs(hub *Hub, w http.ResponseWriter, r *http.Request, sandboxID string) {
	conn, err := upgrader.Upgrade(w, r, nil) // upgrader needs to be defined globally or passed in
	if err != nil {
		hub.logger.Error("Failed to upgrade WebSocket connection", "error", err)
		return
	}
	client := &Client{sandboxID: sandboxID, hub: hub, conn: conn, send: make(chan []byte, 256)}
	hub.register <- client

	// Allow collection of memory referenced by the caller by doing all work in
	// new goroutines.
	go client.writePump()
	go client.readPump()
}

// TODO: Define upgrader (likely in handler or main)
// var upgrader = websocket.Upgrader{
// 	ReadBufferSize:  1024,
// 	WriteBufferSize: 1024,
// 	CheckOrigin: func(r *http.Request) bool {
// 		// Allow all origins for now, adjust in production
// 		return true
// 	},
// }