// Package worker dispatches jobs with bounded work parallelism.
//
// Note: one goroutine is spawned per job at submission; only n run fn
// concurrently (gated by a semaphore). Goroutine count therefore scales
// with len(jobs), not n. Safe at the current HardLimit (1000) but not a
// true fan-out pool — replace with a channel + fixed worker count if
// callers ever exceed a few thousand jobs.
package worker

import (
	"context"
	"fmt"
	"runtime/debug"
	"sync"
)

// PanicErr signals a panic recovered inside a worker goroutine.
type PanicErr struct {
	Value any
	Stack string
}

func (e *PanicErr) Error() string { return fmt.Sprintf("panic: %v", e.Value) }

// Result is a generic completion record. Err is nil on success.
type Result[J any, R any] struct {
	Job   J
	Value R
	Err   error
}

// Run dispatches jobs and emits Results in finish-order on the returned
// channel; at most n run fn concurrently. The channel closes when all jobs
// finish (including panics). External ctx cancellation aborts in-flight
// workers; the chan still closes. See package doc for goroutine-count
// caveat.
func Run[J any, R any](ctx context.Context, n int, jobs []J, fn func(context.Context, J) (R, error)) <-chan Result[J, R] {
	if n < 1 {
		n = 1
	}
	out := make(chan Result[J, R], len(jobs))
	if len(jobs) == 0 {
		close(out)
		return out
	}
	sem := make(chan struct{}, n)
	var wg sync.WaitGroup
	for _, job := range jobs {
		wg.Add(1)
		go func(job J) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				out <- Result[J, R]{Job: job, Err: ctx.Err()}
				return
			}
			defer func() {
				if r := recover(); r != nil {
					out <- Result[J, R]{Job: job, Err: &PanicErr{Value: r, Stack: string(debug.Stack())}}
				}
			}()
			val, err := fn(ctx, job)
			out <- Result[J, R]{Job: job, Value: val, Err: err}
		}(job)
	}
	go func() {
		wg.Wait()
		close(out)
	}()
	return out
}
