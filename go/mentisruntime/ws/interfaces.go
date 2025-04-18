package ws

import (
	"context"
)

// SandboxChecker defines the interface required by the ws package
// to interact with the sandbox manager, specifically for checking
// if a sandbox exists.
// This helps break the import cycle between ws and manager.
type SandboxChecker interface {
	// SandboxExists checks if a sandbox with the given ID exists.
	SandboxExists(ctx context.Context, sandboxID string) (bool, error)
}