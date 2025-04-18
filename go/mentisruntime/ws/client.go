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
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				// The hub closed the channel.
				c.logger.Info("Hub closed the send channel, closing connection")
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			w, err := c.conn.NextWriter(websocket.TextMessage)
			if err != nil {
				c.logger.Error("Failed to get next writer", "error", err)
				return
			}
			_, err = w.Write(message)
			if err != nil {
				c.logger.Error("Failed to write message to websocket", "error", err)
				// Attempt to close the writer even if write failed
				w.Close()
				return
			}

			// Add queued chat messages to the current websocket message.
			n := len(c.send)
			for i := 0; i < n; i++ {
				_, err = w.Write(newline) // Add newline separator between messages if needed
				if err != nil {
					c.logger.Error("Failed to write newline separator", "error", err)
					// Attempt to close the writer even if write failed
					w.Close()
					return
				}
				msgToSend := <-c.send
				_, err = w.Write(msgToSend)
				if err != nil {
					c.logger.Error("Failed to write queued message to websocket", "error", err)
					// Attempt to close the writer even if write failed
					w.Close()
					return
				}
			}

			if err := w.Close(); err != nil {
				c.logger.Error("Failed to close writer", "error", err)
				return
			}
			c.logger.Debug("Message sent to client", "messageSize", len(message))

		case <-ticker.C:
			c.logger.Debug("Sending Ping")
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				c.logger.Error("Failed to write ping message", "error", err)
				return
			}
		}
	}
}