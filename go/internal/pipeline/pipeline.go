// Package pipeline orchestrates the end-to-end run.
package pipeline

import (
	"context"
	"errors"

	"github.com/salamientark/writeme/internal/cli"
	"github.com/salamientark/writeme/internal/state"
)

// ErrNotImplemented is returned by Run until phase 6 lands.
var ErrNotImplemented = errors.New("pipeline.Run not implemented")

// Run orchestrates the full pipeline. Wired in phase 6.
func Run(ctx context.Context, cfg cli.Config, store *state.Store) (state.Summary, error) {
	_ = ctx
	_ = cfg
	if store == nil {
		return state.Summary{}, errors.New("nil store")
	}
	return state.Summary{}, ErrNotImplemented
}
