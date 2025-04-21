package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log" // Import standard log package
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/docker/docker/client" // Docker client
	"github.com/gorilla/mux"          // HTTP router

	// Local packages (adjust paths if necessary)
	"github.com/foreveryh/sandboxai/go/mentisruntime/handler"
	"github.com/foreveryh/sandboxai/go/mentisruntime/manager"
	"github.com/foreveryh/sandboxai/go/mentisruntime/ws"

	// Specific client for cleanup, separate from the manager's client
	cleanupdocker "github.com/foreveryh/sandboxai/go/mentisruntime/client/docker"
)

func main() {
	// --- Configuration --- 
	host, ok := os.LookupEnv("SANDBOXAID_HOST")
	if !ok {
		host = "127.0.0.1"
	}
	port, ok := os.LookupEnv("SANDBOXAID_PORT")
	if !ok {
		port = "5266"
	}
	scope, ok := os.LookupEnv("SANDBOXAID_SCOPE")
	if !ok {
		scope = "default"
	}
	var deleteOnShutdown bool
	if val, ok := os.LookupEnv("SANDBOXAID_DELETE_ON_SHUTDOWN"); ok {
		deleteOnShutdown = strings.ToLower(strings.TrimSpace(val)) == "true"
	}

	// --- Logger --- 
	logger := slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelDebug}))
	slog.SetDefault(logger)

	// --- Initialize Managers ---
	// Create Docker client
	dockerClient, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		logger.Error("Failed to create Docker client", "error", err)
		os.Exit(1)
	}
	logger.Info("Docker client initialized")
	
	// Create WebSocket hub
	hub := ws.NewHub(logger)
	go hub.Run()
	logger.Info("WebSocket hub started")

	// Create Space Manager first
	spaceManager := manager.NewSpaceManager(logger)
	logger.Info("Space manager initialized")
	
	// Create Sandbox Manager (depends on Space Manager)
	sandboxManager, err := manager.NewSandboxManager(
		context.Background(),
		dockerClient,
		hub,
		spaceManager, // Add SpaceManager parameter
		logger,
		os.Getenv("SANDBOX_SCOPE"),
	)
	if err != nil {
		logger.Error("Failed to create sandbox manager", "error", err)
		os.Exit(1)
	}
	logger.Info("Sandbox manager initialized")

	// --- Initialize API Handler ---
	apiHandler := handler.NewAPIHandler(logger, sandboxManager, spaceManager, hub)
	logger.Info("API handler initialized")

	// --- Router --- 
	router := mux.NewRouter()

	// Register handlers
	api := router.PathPrefix("/v1").Subrouter()
	api.HandleFunc("/health", handler.HealthCheckHandler).Methods("GET")

	// Space routes (using chi style params)
	api.HandleFunc("/spaces", apiHandler.CreateSpaceHandler).Methods("POST")
	api.HandleFunc("/spaces", apiHandler.ListSpacesHandler).Methods("GET")
	api.HandleFunc("/spaces/{spaceID}", apiHandler.GetSpaceHandler).Methods("GET")
	api.HandleFunc("/spaces/{spaceID}", apiHandler.UpdateSpaceHandler).Methods("PUT")
	api.HandleFunc("/spaces/{spaceID}", apiHandler.DeleteSpaceHandler).Methods("DELETE")

	// Sandbox routes (associated with a space, using chi style params)
	api.HandleFunc("/spaces/{spaceID}/sandboxes", apiHandler.CreateSandboxHandler).Methods("POST")
	api.HandleFunc("/spaces/{spaceID}/sandboxes/{sandboxID}", apiHandler.GetSandboxHandler).Methods("GET")    // Added GET sandbox
	api.HandleFunc("/spaces/{spaceID}/sandboxes/{sandboxID}", apiHandler.DeleteSandboxHandler).Methods("DELETE") // Corrected DELETE sandbox path

	// Action routes (associated with a specific sandbox)
	api.HandleFunc("/spaces/{spaceID}/sandboxes/{sandboxID}/tools:run_shell_command", apiHandler.PostShellCommandHandler).Methods("POST") // Corrected shell path
	api.HandleFunc("/spaces/{spaceID}/sandboxes/{sandboxID}/tools:run_ipython_cell", apiHandler.PostIPythonCellHandler).Methods("POST") // Corrected ipython path

	// Internal Observation Route
	api.HandleFunc("/internal/observations/{sandboxID}", apiHandler.InternalObservationHandler).Methods("POST") // Changed to sandboxID

	// WebSocket Route (associated with a specific sandbox)
	router.HandleFunc("/v1/sandboxes/{sandboxID}/stream", func(w http.ResponseWriter, r *http.Request) { // Changed to sandboxID
		// Assuming ServeWs signature: hub, checker, w, r, logger
		// Pass sandboxManager as it implements the SandboxChecker interface
		ws.ServeWs(hub, sandboxManager, w, r, logger)
	})

	// --- Cleanup Logic (using separate, original client) --- 
	if deleteOnShutdown {
		defer func() {
			logger.Info("Cleanup: Ensuring all sandboxes are deleted")
			// Use the original docker client specifically for cleanup as manager might not expose ListAll
			cleanupClient, cleanupErr := cleanupdocker.NewSandboxClient(nil, &http.Client{}, scope)
			if cleanupErr != nil {
				logger.Error("Cleanup: Failed to create sandbox client for cleanup", "error", cleanupErr)
				return
			}
			cleanupdocker.SetLogger(log.New(os.Stderr, "[cleanup-client] ", log.LstdFlags)) // Use stdlib log for cleanup client

			cleanupCtx, cancelCleanup := context.WithTimeout(context.Background(), 1*time.Minute)
			defer cancelCleanup()
			refs, err := cleanupClient.ListAllSandboxes(cleanupCtx)
			if err != nil {
				logger.Error("Cleanup: Failed to list sandbox IDs", "error", err)
				return
			}
			if len(refs) == 0 {
				logger.Info("Cleanup: No sandboxes to delete")
				return
			}
			logger.Info("Cleanup: Starting deletion", "count", len(refs))
			for i, ref := range refs {
				logger.Info("Cleanup: Deleting sandbox", "index", i+1, "total", len(refs), "id", ref.Name, "space", ref.Space)
				// Use the specific cleanup client's delete method
				if err := cleanupClient.DeleteSandbox(context.Background(), ref.Space, ref.Name); err != nil {
					logger.Error("Cleanup: Failed to delete sandbox", "id", ref.Name, "space", ref.Space, "error", err)
					// Continue trying to delete others
				}
			}
			logger.Info("Cleanup: Finished deleting sandboxes", "deleted_count", len(refs))
		}()
	}

	// --- HTTP Server --- 
	server := &http.Server{
		Addr:    fmt.Sprintf("%s:%s", host, port),
		Handler: router, // Use the mux router
	}

	// --- Start Server Goroutine --- 
	go func() {
		ln, err := net.Listen("tcp", server.Addr)
		if err != nil {
			logger.Error("Failed to listen", "address", server.Addr, "error", err)
			os.Exit(1)
		}
		addr := ln.Addr().(*net.TCPAddr)
		if port == "0" {
			// If "any free port" was specified, output the selected port.
			if err := json.NewEncoder(os.Stdout).Encode(serverInfo{Host: addr.IP.String(), Port: addr.Port}); err != nil {
				logger.Error("Failed to output server info", "error", err)
				os.Exit(1)
			}
		}
		logger.Info("Listening and starting HTTP server", "address", addr.String())
		if err := server.Serve(ln); !errors.Is(err, http.ErrServerClosed) {
			logger.Error("HTTP server error", "error", err)
			os.Exit(1)
		}
		logger.Info("Stopped serving new connections")
	}()

	// --- Graceful Shutdown --- 
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigChan

	gracePeriod := 30 * time.Second
	shutdownCtx, shutdownRelease := context.WithTimeout(context.Background(), gracePeriod)
	defer shutdownRelease()

	logger.Info("Received signal, shutting down", "signal", sig.String(), "grace_period", gracePeriod)

	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("Error shutting down HTTP server", "error", err)
		os.Exit(1) // Exit with error on shutdown failure
	}
	logger.Info("Graceful shutdown complete")
}

// serverInfo is outputted to stdout so that the program that started the server can determine
// the address it is listening on when ports are auto-selected.
type serverInfo struct {
	Host string `json:"host"`
	Port int    `json:"port"`
}
