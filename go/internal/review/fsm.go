package review

import (
	"context"
	"errors"
)

// Decision enumerates terminal FSM outcomes.
type Decision string

const (
	DecisionAccepted Decision = "accepted"
	DecisionSkipped  Decision = "skipped"
	DecisionFailed   Decision = "failed"
	DecisionQuit     Decision = "quit"
)

// SessionResult is the terminal value of one review loop.
type SessionResult struct {
	Decision Decision
	Reason   string
}

// Prompter abstracts all interactive prompts so the FSM stays pure & testable.
// All methods must honor ctx cancellation (return ctx.Err()).
type Prompter interface {
	RiskyFiles(ctx context.Context, risky []string) (string, error)              // "c"|"s"
	Timeout(ctx context.Context) (string, error)                                 // "r"|"s"|"q"
	Nonzero(ctx context.Context) (string, error)                                 // "r"|"d"
	SecretOverride(ctx context.Context, matches []string) (bool, error)          // true ⇒ "yes-i-checked"
	Accept(ctx context.Context, hadReadme bool, old, new string) (string, error) // "a"|"r"|"d"|"q"
}

// Generator regenerates a draft for redo / retry iterations. prevDraft is the
// content of the previous draft (empty on first regen for a timeout retry).
type Generator func(ctx context.Context, prevDraft string) (GenerationResult, error)

// Cleaner reverts the working tree on non-accept exits.
type Cleaner func(ctx context.Context, repoDir string) error

// SessionConfig parameterises Loop.
type SessionConfig struct {
	RepoDir         string
	RepoName        string
	HadReadmeBefore bool
	Pregenerated    *GenerationResult
	Generator       Generator
	Prompter        Prompter
	Cleaner         Cleaner
	OnRedo          func(prevDraft string) // optional: notified when redo occurs
}

// Loop runs the review FSM for a single repo.
func Loop(ctx context.Context, cfg SessionConfig) SessionResult {
	if cfg.Cleaner == nil {
		cfg.Cleaner = func(context.Context, string) error { return nil }
	}
	clean := func(reason string) SessionResult {
		_ = cfg.Cleaner(ctx, cfg.RepoDir)
		return SessionResult{Decision: DecisionSkipped, Reason: reason}
	}

	var (
		oldContent string
		prevDraft  string
		pre        = cfg.Pregenerated
	)
	if pre != nil {
		oldContent = pre.OldContent
	}

	riskyChecked := false
	// Pre-loop risky scan: derived from first GenerationResult.
	if pre != nil && len(pre.RiskyFiles) > 0 {
		choice, err := cfg.Prompter.RiskyFiles(ctx, pre.RiskyFiles)
		if err != nil {
			return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
		}
		if choice == "s" {
			return clean("risky_files_found")
		}
		riskyChecked = true
	}

	for {
		if err := ctx.Err(); err != nil {
			return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
		}

		var gen GenerationResult
		if pre != nil {
			gen = *pre
			pre = nil
		} else {
			if cfg.Generator == nil {
				return SessionResult{Decision: DecisionFailed, Reason: "no_generator"}
			}
			g, err := cfg.Generator(ctx, prevDraft)
			if err != nil {
				if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
					return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
				}
				return SessionResult{Decision: DecisionFailed, Reason: err.Error()}
			}
			gen = g
			if oldContent == "" {
				oldContent = gen.OldContent
			}
		}

		if !riskyChecked && len(gen.RiskyFiles) > 0 {
			choice, err := cfg.Prompter.RiskyFiles(ctx, gen.RiskyFiles)
			if err != nil {
				return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
			}
			if choice == "s" {
				return clean("risky_files_found")
			}
		}
		riskyChecked = true

		switch gen.Status {
		case StatusTimeout:
			c, err := cfg.Prompter.Timeout(ctx)
			if err != nil {
				return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
			}
			switch c {
			case "r":
				continue
			case "s":
				return clean("claude_timeout")
			default: // "q"
				return SessionResult{Decision: DecisionQuit, Reason: "claude_timeout"}
			}

		case StatusNonzero:
			c, err := cfg.Prompter.Nonzero(ctx)
			if err != nil {
				return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
			}
			if c == "r" {
				continue
			}
			return clean("claude_nonzero_exit")

		case StatusBlastRadius:
			reason := gen.Error
			if reason == "" {
				reason = "claude_touched_other_files"
			}
			_ = cfg.Cleaner(ctx, cfg.RepoDir)
			return SessionResult{Decision: DecisionFailed, Reason: reason}

		case StatusFailed:
			reason := gen.Error
			if reason == "" {
				reason = "generation_failed"
			}
			_ = cfg.Cleaner(ctx, cfg.RepoDir)
			return SessionResult{Decision: DecisionFailed, Reason: reason}

		case StatusReady:
			if len(gen.SecretMatches) > 0 {
				ok, err := cfg.Prompter.SecretOverride(ctx, gen.SecretMatches)
				if err != nil {
					return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
				}
				if !ok {
					return clean("secrets_detected")
				}
			}
			c, err := cfg.Prompter.Accept(ctx, cfg.HadReadmeBefore, oldContent, gen.NewContent)
			if err != nil {
				return SessionResult{Decision: DecisionQuit, Reason: err.Error()}
			}
			switch c {
			case "a":
				return SessionResult{Decision: DecisionAccepted}
			case "d":
				return clean("user_discarded")
			case "q":
				_ = cfg.Cleaner(ctx, cfg.RepoDir)
				return SessionResult{Decision: DecisionQuit, Reason: "user_quit"}
			case "r":
				prevDraft = gen.NewContent
				if cfg.OnRedo != nil {
					cfg.OnRedo(prevDraft)
				}
				continue
			default:
				return clean("user_discarded")
			}
		default:
			return SessionResult{Decision: DecisionFailed, Reason: "unknown_status"}
		}
	}
}
