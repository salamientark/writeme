// Package unpushed scans the repos cache for dirty trees / unpushed commits.
package unpushed

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// Finding describes one repo with unpushed work.
type Finding struct {
	Path            string
	Dirty           bool
	UnpushedCommits int
}

// Scan returns sorted findings under reposDir.
// Non-git directories silently skipped. Clones with no upstream are
// checked for dirtiness only.
func Scan(ctx context.Context, reposDir string) ([]Finding, error) {
	entries, err := os.ReadDir(reposDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var out []Finding
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(reposDir, e.Name())
		if _, err := os.Stat(filepath.Join(dir, ".git")); err != nil {
			continue
		}
		dirty := isDirty(ctx, dir)
		unpushed := 0
		if hasUpstream(ctx, dir) {
			unpushed = unpushedCount(ctx, dir)
		}
		if dirty || unpushed > 0 {
			out = append(out, Finding{Path: dir, Dirty: dirty, UnpushedCommits: unpushed})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	return out, nil
}

func runGit(ctx context.Context, dir string, args ...string) (string, int) {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	out, err := cmd.Output()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		code = -1
	}
	return string(out), code
}

func isDirty(ctx context.Context, dir string) bool {
	out, _ := runGit(ctx, dir, "status", "--porcelain")
	return strings.TrimSpace(out) != ""
}

func hasUpstream(ctx context.Context, dir string) bool {
	_, code := runGit(ctx, dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
	return code == 0
}

func unpushedCount(ctx context.Context, dir string) int {
	out, code := runGit(ctx, dir, "rev-list", "--count", "@{u}..HEAD")
	if code != 0 {
		return 0
	}
	n, err := strconv.Atoi(strings.TrimSpace(out))
	if err != nil {
		return 0
	}
	return n
}
