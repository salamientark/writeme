package pipeline

import (
	"context"

	"github.com/salamientark/writeme/internal/review"
	"github.com/salamientark/writeme/internal/ui"
)

// runReviewFn is the signature of the function that launches the review TUI.
type runReviewFn func(ui.ReviewContext) ui.ReviewDecision

// tuiPrompter wraps a Prompter, delegating the Accept prompt to the TUI review screen.
type tuiPrompter struct {
	inner     review.Prompter
	repoName  string
	index     int
	total     int
	runReview runReviewFn
}

// NewTUIPrompter creates a Prompter that uses the TUI for the Accept step.
func NewTUIPrompter(inner review.Prompter, repoName string, index, total int) review.Prompter {
	return &tuiPrompter{inner: inner, repoName: repoName, index: index, total: total, runReview: ui.RunReview}
}

func (p *tuiPrompter) RiskyFiles(ctx context.Context, risky []string) (string, error) {
	return p.inner.RiskyFiles(ctx, risky)
}

func (p *tuiPrompter) Timeout(ctx context.Context) (string, error) {
	return p.inner.Timeout(ctx)
}

func (p *tuiPrompter) Nonzero(ctx context.Context) (string, error) {
	return p.inner.Nonzero(ctx)
}

func (p *tuiPrompter) SecretOverride(ctx context.Context, matches []string) (bool, error) {
	return p.inner.SecretOverride(ctx, matches)
}

func (p *tuiPrompter) Accept(ctx context.Context, hadReadme bool, old, new string) (string, error) {
	// Use the TUI review screen for the accept decision.
	var headReadme *string
	if hadReadme {
		h := old
		headReadme = &h
	}
	ctx2 := ui.ReviewContext{
		RepoName:     p.repoName,
		Index:        p.index,
		Total:        p.total,
		HeadReadme:   headReadme,
		CurrentDraft: new,
	}
	decision := p.runReview(ctx2)
	switch decision {
	case ui.ReviewAccept:
		return "a", nil
	case ui.ReviewRedo:
		return "r", nil
	case ui.ReviewDiscard:
		return "d", nil
	default:
		return "q", nil
	}
}
