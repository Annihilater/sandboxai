package manager

import (
	"context"
	"log/slog"
	"sync"
	"time"

	"github.com/google/uuid"
)

// SpaceManager manages spaces.
type SpaceManager struct {
	mu     sync.RWMutex
	spaces map[string]*SpaceState
	logger *slog.Logger
}

// NewSpaceManager creates a new SpaceManager.
func NewSpaceManager(logger *slog.Logger) *SpaceManager {
	sm := &SpaceManager{
		spaces: make(map[string]*SpaceState),
		logger: logger.With("component", "space-manager"),
	}
	// Create default space if it doesn't exist
	defaultSpace := &SpaceState{
		ID:        "default",
		Name:      "Default Space",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
		Sandboxes: make(map[string]*SandboxState),
	}
	sm.spaces["default"] = defaultSpace
	sm.logger.Info("Default space created")
	return sm
}

// CreateSpace creates a new space.
func (sm *SpaceManager) CreateSpace(ctx context.Context, name string, description string, metadata map[string]interface{}) (string, error) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	// Check for name conflict (optional, but good practice)
	for _, existingSpace := range sm.spaces {
		if existingSpace.Name == name {
			sm.logger.Warn("Attempted to create space with conflicting name", "name", name)
			return "", ErrSpaceNameConflict
		}
	}

	spaceID := uuid.NewString()
	space := &SpaceState{
		ID:          spaceID,
		Name:        name,
		Description: description,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
		Metadata:    metadata,
		Sandboxes:   make(map[string]*SandboxState),
	}

	sm.spaces[spaceID] = space
	sm.logger.Info("Space created", "spaceID", spaceID, "name", name)
	return spaceID, nil
}

// GetSpace retrieves a space by ID.
func (sm *SpaceManager) GetSpace(ctx context.Context, spaceID string) (*SpaceState, error) {
	sm.mu.RLock()
	defer sm.mu.RUnlock()

	space, exists := sm.spaces[spaceID]
	if !exists {
		return nil, ErrSpaceNotFound
	}
	// Return a copy to prevent external modification? For now, return pointer. Be mindful of modifications.
	// Let's return a shallow copy for now, deep copy might be needed depending on usage
	spaceCopy := *space
	// If Metadata or Sandboxes can be modified externally, deep copy them here.
	// Example shallow copy:
	return &spaceCopy, nil
}

// ListSpaces returns all spaces.
func (sm *SpaceManager) ListSpaces(ctx context.Context) ([]*SpaceState, error) {
	sm.mu.RLock()
	defer sm.mu.RUnlock()

	spaces := make([]*SpaceState, 0, len(sm.spaces))
	for _, space := range sm.spaces {
		// Return copies to prevent external modification
		spaceCopy := *space // Shallow copy
		// Deep copy Metadata/Sandboxes if necessary
		spaces = append(spaces, &spaceCopy)
	}

	return spaces, nil
}

// UpdateSpace updates a space's description and metadata.
func (sm *SpaceManager) UpdateSpace(ctx context.Context, spaceID string, description string, metadata map[string]interface{}) error {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	space, exists := sm.spaces[spaceID]
	if !exists {
		return ErrSpaceNotFound
	}

	// Update fields
	space.Description = description
	space.Metadata = metadata // Overwrite or merge? Currently overwrites.
	space.UpdatedAt = time.Now()

	sm.logger.Info("Space updated", "spaceID", spaceID)
	return nil
}

// DeleteSpace deletes a space.
// Note: This currently doesn't handle deleting associated sandboxes.
// That logic might belong in SandboxManager or require coordination.
// **UPDATE**: We will coordinate this from SandboxManager.DeleteSpace now.
func (sm *SpaceManager) DeleteSpace(ctx context.Context, spaceID string) error {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if _, exists := sm.spaces[spaceID]; !exists {
		return ErrSpaceNotFound
	}

	// The actual deletion of sandboxes should be handled by the caller (e.g., SandboxManager)
	// before calling this method, or this method needs access to SandboxManager.
	// For now, just delete the space entry.

	delete(sm.spaces, spaceID)
	sm.logger.Info("Space deleted from SpaceManager", "spaceID", spaceID)
	return nil
}

// --- Methods needed by SandboxManager ---

// addSandboxToSpace adds a sandbox reference to a space. Internal use by SandboxManager.
func (sm *SpaceManager) addSandboxToSpace(spaceID string, sandboxID string, sandboxState *SandboxState) error {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	space, exists := sm.spaces[spaceID]
	if !exists {
		return ErrSpaceNotFound
	}
	if space.Sandboxes == nil {
		space.Sandboxes = make(map[string]*SandboxState)
	}
	space.Sandboxes[sandboxID] = sandboxState
	sm.logger.Debug("Added sandbox reference to space", "spaceID", spaceID, "sandboxID", sandboxID)
	return nil
}

// removeSandboxFromSpace removes a sandbox reference from a space. Internal use by SandboxManager.
func (sm *SpaceManager) removeSandboxFromSpace(spaceID string, sandboxID string) error {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	space, exists := sm.spaces[spaceID]
	if !exists {
		// Log warning but don't return error, space might be deleted already
		sm.logger.Warn("Space not found while trying to remove sandbox reference", "spaceID", spaceID, "sandboxID", sandboxID)
		return nil
	}
	if space.Sandboxes != nil {
		delete(space.Sandboxes, sandboxID)
		sm.logger.Debug("Removed sandbox reference from space", "spaceID", spaceID, "sandboxID", sandboxID)
	}
	return nil
}

// getSpaceSandboxes returns the sandbox IDs for a given space. Internal use by SandboxManager.
func (sm *SpaceManager) getSpaceSandboxes(spaceID string) ([]string, error) {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	space, exists := sm.spaces[spaceID]
	if !exists {
		return nil, ErrSpaceNotFound
	}
	ids := make([]string, 0, len(space.Sandboxes))
	for id := range space.Sandboxes {
		ids = append(ids, id)
	}
	return ids, nil
}