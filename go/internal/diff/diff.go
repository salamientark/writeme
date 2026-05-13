// Package diff renders plain-text diffs of README.md.
package diff

import (
	"context"
	"fmt"
	"os/exec"
	"strings"

	"github.com/hexops/gotextdiff"
	"github.com/hexops/gotextdiff/myers"
	"github.com/hexops/gotextdiff/span"
)

// Sentinels for edge cases.
const (
	NoHeadDiff = "(no diff — first draft, no prior README)"
	NoPrevDiff = "(no diff — this is the first draft)"
	NoChanges  = "(no changes)"
)

const (
	draftLabel = "README.md (draft)"
	headLabel  = "README.md (HEAD)"
	prevLabel  = "README.md (prev draft)"
)

// Unified returns a unified diff between old and new, or NoChanges sentinel.
func Unified(old, new, fromfile, tofile string) string {
	if old == new {
		return NoChanges
	}
	edits := myers.ComputeEdits(span.URIFromPath(fromfile), old, new)
	diff := fmt.Sprint(gotextdiff.ToUnified(fromfile, tofile, old, edits))
	if diff == "" {
		return NoChanges
	}
	return strings.TrimRight(diff, "\n")
}

// DiffVsHead diffs committed README against current draft. Falls back if no HEAD README.
func DiffVsHead(head *string, current string) string {
	if head == nil {
		return NoHeadDiff
	}
	return Unified(*head, current, headLabel, draftLabel)
}

// DiffVsPrev diffs previous Claude draft against current. Falls back on first iteration.
func DiffVsPrev(prev *string, current string) string {
	if prev == nil {
		return NoPrevDiff
	}
	return Unified(*prev, current, prevLabel, draftLabel)
}

// Plain returns `git diff --no-color README.md` from repoDir.
func Plain(ctx context.Context, repoDir string) (string, error) {
	cmd := exec.CommandContext(ctx, "git", "diff", "--no-color", "README.md")
	cmd.Dir = repoDir
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git diff: %w", err)
	}
	return string(out), nil
}
