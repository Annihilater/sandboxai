package ws

import (
	"bytes"
	"log/slog"
	"net/http"
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

var (
	newline = []byte{ '\n' }
	space   = []byte{ ' ' }
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	// CheckOrigin should be implemented for production environments
	// to prevent CSRF attacks. For now, allow all origins.
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// Client is a middleman between the websocket connection and the hub.
type Client struct {
	hub *Hub

	// The websocket connection.
	conn *websocket.Conn

	// Buffered channel of outbound messages.
	send chan []byte

	// The sandbox ID this client is associated with.
	sandboxID string

	logger *slog.Logger
}

// readPump pumps messages from the websocket connection to the hub.
//
// The application runs readPump in a per-connection goroutine. The application
// ensures that there is at most one reader on a connection by executing all
// reads from this goroutine.
func (c *Client) readPump() {
	defer func() {
		c.hub.unregister <- c
		c.conn.Close()
		c.logger.Debug("readPump finished, client unregistered and connection closed")
	}()
	c.conn.SetReadLimit(maxMessageSize)
	c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error { 
		c.logger.Debug("Pong received")
		c.conn.SetReadDeadline(time.Now().Add(pongWait)); 
		return nil 
	})
	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				c.logger.Error("WebSocket read error", "error", err)
			} else {
				c.logger.Info("WebSocket connection closed", "error", err)
			}
			break
		}
		message = bytes.TrimSpace(bytes.Replace(message, newline, space, -1))
		// We don't expect messages from the client in this model, but log if received.
		c.logger.Warn("Received unexpected message from client", "message", string(message))
		// If client messages were expected, they would be processed here, potentially
		// involving the hub or manager.
		// c.hub.processClientMessage <- &ClientMessage{client: c, message: message}
	}
}

// writePump pumps messages from the hub to the websocket connection.
//
// A goroutine running writePump is started for each connection. The
// application ensures that there is at most one writer to a connection by
// executing all writes from this goroutine.
func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.conn.Close()
		c.logger.Debug("writePump finished, ticker stopped and connection closed")
	}()
	for {
		select {
		case message, ok := <-c.send:
			// Set write deadline before attempting to write
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				// The hub closed the channel. Send a close message.
				c.logger.Info("Hub closed the send channel, sending close message")
				// Best effort to send close frame, ignore error
				_ = c.conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
				return // Exit goroutine
			}

			// Write the message as a single, distinct WebSocket text message.
			// Removed the loop that aggregated multiple messages into one frame.
			err := c.conn.WriteMessage(websocket.TextMessage, message)
			if err != nil {
				// Log error and assume connection is broken, exit goroutine.
				// readPump will handle unregistering the client.
				if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure, websocket.CloseNormalClosure) {
					c.logger.Error("Failed to write message to websocket", "error", err)
				} else {
					c.logger.Info("Failed to write message, connection likely closed", "error", err)
				}
				return // Exit goroutine
			}
			c.logger.Debug("Message sent to client", "messageSize", len(message))

		case <-ticker.C:
			// Send ping message
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				// Log error and assume connection is broken, exit goroutine.
				// readPump will handle unregistering the client.
				c.logger.Error("Failed to write ping message", "error", err)
				return // Exit goroutine
			}
			c.logger.Debug("Sending Ping")
		}
	}
}