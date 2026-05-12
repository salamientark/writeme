// Package sandbox: per-job XDG sandbox dirs for parallel claude invocations.
package sandbox

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/salamientark/writeme/internal/safety"
)

// SubDirs are the four XDG sub-directories laid down per job.
var SubDirs = []string{"config", "data", "cache", "state"}

// Job represents a per-repo XDG sandbox tree.
type Job struct {
	Root  string
	Paths map[string]string
}

// JobSandbox creates <base>/claude-jobs/<repo>/{config,data,cache,state}.
func JobSandbox(base, repoName string) (*Job, error) {
	if err := safety.ValidateRepoName(repoName); err != nil {
		return nil, err
	}
	root := filepath.Join(base, "claude-jobs", repoName)
	paths := map[string]string{}
	for _, name := range SubDirs {
		p := filepath.Join(root, name)
		if err := os.MkdirAll(p, 0o755); err != nil {
			return nil, fmt.Errorf("mkdir %s: %w", p, err)
		}
		paths[name] = p
	}
	return &Job{Root: root, Paths: paths}, nil
}

// EnvFor returns the XDG_*_HOME overrides for the claude subprocess.
func EnvFor(job *Job) []string {
	return []string{
		"XDG_CONFIG_HOME=" + job.Paths["config"],
		"XDG_DATA_HOME=" + job.Paths["data"],
		"XDG_CACHE_HOME=" + job.Paths["cache"],
		"XDG_STATE_HOME=" + job.Paths["state"],
	}
}

// Cleanup removes the per-job sandbox tree (idempotent).
func (j *Job) Cleanup() error { return os.RemoveAll(j.Root) }
