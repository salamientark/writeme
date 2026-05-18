// Package safety: input validation, repo cleanup, advisory locking, blast-radius.
package safety

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var (
	repoNameRe  = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)
	httpsURLRe  = regexp.MustCompile(`^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$`)
	sshURLRe    = regexp.MustCompile(`^git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$`)
	reservedSet = map[string]bool{".": true, "..": true}
)

// ErrLocked indicates the lock is already held by another process.
var ErrLocked = errors.New("lock held by another process")

// ValidateRepoName rejects empty, ".", "..", and any name with shell/path metacharacters.
func ValidateRepoName(name string) error {
	if name == "" {
		return errors.New("repo name must not be empty")
	}
	if reservedSet[name] {
		return fmt.Errorf("unsafe repo name (reserved): %q", name)
	}
	if !repoNameRe.MatchString(name) {
		return fmt.Errorf("unsafe repo name (invalid characters): %q", name)
	}
	return nil
}

// ValidateSSHURL rejects all clone URLs except canonical github.com SSH/HTTPS forms.
func ValidateSSHURL(url string) error {
	if url == "" {
		return errors.New("clone URL must not be empty")
	}
	if httpsURLRe.MatchString(url) || sshURLRe.MatchString(url) {
		return nil
	}
	return fmt.Errorf("unexpected clone URL: %q", url)
}

// EnsureClean resets repoDir to HEAD, drops untracked files, removes operation markers.
func EnsureClean(ctx context.Context, repoDir string) error {
	for _, args := range [][]string{
		{"git", "reset", "--hard", "HEAD"},
		{"git", "clean", "-fd"},
	} {
		cmd := exec.CommandContext(ctx, args[0], args[1:]...)
		cmd.Dir = repoDir
		_ = cmd.Run() // mirror Python: check=False
	}
	for _, marker := range []string{"MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD"} {
		_ = os.Remove(filepath.Join(repoDir, ".git", marker))
	}
	return nil
}

// AcquireLock takes an exclusive non-blocking advisory lock on path. Returns
// a release func. Platform-specific implementations live in lock_unix.go and
// lock_windows.go.

// BlastRadius parses git status --porcelain -z and returns sorted touched paths
// excluding README.md. Empty result = clean to ship.
func BlastRadius(ctx context.Context, repoDir string) ([]string, error) {
	cmd := exec.CommandContext(ctx, "git", "status", "--porcelain", "-z")
	cmd.Dir = repoDir
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("git status: %w", err)
	}
	var paths []string
	tokens := strings.Split(string(out), "\x00")
	for i := 0; i < len(tokens); i++ {
		entry := tokens[i]
		if len(entry) < 4 {
			continue
		}
		path := entry[3:]
		// Rename (R) and copy (C) records emit "<XY> <new>\0<old>\0".
		// Consume the trailing old-path token so it doesn't get re-parsed
		// as if it had a status prefix.
		if entry[0] == 'R' || entry[0] == 'C' || entry[1] == 'R' || entry[1] == 'C' {
			if i+1 < len(tokens) {
				old := tokens[i+1]
				i++
				if old != "" && old != "README.md" {
					paths = append(paths, old)
				}
			}
		}
		if path == "README.md" {
			continue
		}
		paths = append(paths, path)
	}
	sort.Strings(paths)
	return paths, nil
}
