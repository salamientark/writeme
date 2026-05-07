// Package diff renders plain-text diffs of README.md.
package diff

import (
	"context"
	"fmt"
	"os/exec"
)

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
