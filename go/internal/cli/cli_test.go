package cli

import (
	"bytes"
	"errors"
	"path/filepath"
	"testing"
)

func envFromMap(m map[string]string) Env {
	return func(k string) (string, bool) {
		v, ok := m[k]
		return v, ok
	}
}

func TestParseDefaults(t *testing.T) {
	env := envFromMap(map[string]string{"HOME": "/h"})
	cfg, err := Parse(nil, env, &bytes.Buffer{})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if cfg.Mode != ModeUnset {
		t.Errorf("Mode=%q want empty", cfg.Mode)
	}
	if cfg.ClaudeTimeout != DefaultTimeout {
		t.Errorf("Timeout=%d", cfg.ClaudeTimeout)
	}
	if cfg.Parallel != DefaultParallel {
		t.Errorf("Parallel=%d", cfg.Parallel)
	}
	if cfg.Limit != DefaultLimit {
		t.Errorf("Limit=%d", cfg.Limit)
	}
	want := filepath.Join("/h", ".cache", AppName, "repos")
	if cfg.ReposDir != want {
		t.Errorf("ReposDir=%q want %q", cfg.ReposDir, want)
	}
}

func TestParsePrecedence(t *testing.T) {
	tests := []struct {
		name    string
		argv    []string
		env     map[string]string
		check   func(*testing.T, Config)
		wantErr bool
	}{
		{
			name: "flag wins over env (parallel)",
			argv: []string{"--parallel=5"},
			env:  map[string]string{"HOME": "/h", "WRITEME_PARALLEL": "2"},
			check: func(t *testing.T, c Config) {
				if c.Parallel != 5 {
					t.Errorf("got %d", c.Parallel)
				}
			},
		},
		{
			name: "env used when flag absent",
			env:  map[string]string{"HOME": "/h", "WRITEME_PARALLEL": "7"},
			check: func(t *testing.T, c Config) {
				if c.Parallel != 7 {
					t.Errorf("got %d", c.Parallel)
				}
			},
		},
		{
			name: "parallel clamp high",
			argv: []string{"--parallel=99"},
			env:  map[string]string{"HOME": "/h"},
			check: func(t *testing.T, c Config) {
				if c.Parallel != ParallelCap {
					t.Errorf("got %d want %d", c.Parallel, ParallelCap)
				}
			},
		},
		{
			name: "parallel clamp low",
			argv: []string{"--parallel=0"},
			env:  map[string]string{"HOME": "/h"},
			check: func(t *testing.T, c Config) {
				if c.Parallel != 1 {
					t.Errorf("got %d", c.Parallel)
				}
			},
		},
		{
			name: "invalid env parallel falls back to default",
			env:  map[string]string{"HOME": "/h", "WRITEME_PARALLEL": "abc"},
			check: func(t *testing.T, c Config) {
				if c.Parallel != DefaultParallel {
					t.Errorf("got %d", c.Parallel)
				}
			},
		},
		{
			name: "claude-timeout invalid env → default",
			env:  map[string]string{"HOME": "/h", "CLAUDE_TIMEOUT": "xx"},
			check: func(t *testing.T, c Config) {
				if c.ClaudeTimeout != DefaultTimeout {
					t.Errorf("got %d", c.ClaudeTimeout)
				}
			},
		},
		{
			name: "claude-timeout flag wins",
			argv: []string{"--claude-timeout=42"},
			env:  map[string]string{"HOME": "/h", "CLAUDE_TIMEOUT": "10"},
			check: func(t *testing.T, c Config) {
				if c.ClaudeTimeout != 42 {
					t.Errorf("got %d", c.ClaudeTimeout)
				}
			},
		},
		{
			name: "skip-ci via env truthy",
			env:  map[string]string{"HOME": "/h", "SKIP_CI": "1"},
			check: func(t *testing.T, c Config) {
				if !c.SkipCI {
					t.Error("want true")
				}
			},
		},
		{
			name: "skip-ci env empty → false",
			env:  map[string]string{"HOME": "/h", "SKIP_CI": ""},
			check: func(t *testing.T, c Config) {
				if c.SkipCI {
					t.Error("want false")
				}
			},
		},
		{
			name: "limit cap",
			env:  map[string]string{"HOME": "/h", "LIMIT": "5000"},
			check: func(t *testing.T, c Config) {
				if c.Limit != HardLimit {
					t.Errorf("got %d", c.Limit)
				}
			},
		},
		{
			name: "limit invalid → default",
			env:  map[string]string{"HOME": "/h", "LIMIT": "wat"},
			check: func(t *testing.T, c Config) {
				if c.Limit != DefaultLimit {
					t.Errorf("got %d", c.Limit)
				}
			},
		},
		{
			name: "repos-dir flag wins",
			argv: []string{"--repos-dir=/a"},
			env:  map[string]string{"HOME": "/h", "GH_README_REPOS_DIR": "/b"},
			check: func(t *testing.T, c Config) {
				if c.ReposDir != "/a" {
					t.Errorf("got %q", c.ReposDir)
				}
			},
		},
		{
			name: "repos-dir env used when flag empty",
			env:  map[string]string{"HOME": "/h", "GH_README_REPOS_DIR": "/b"},
			check: func(t *testing.T, c Config) {
				if c.ReposDir != "/b" {
					t.Errorf("got %q", c.ReposDir)
				}
			},
		},
		{
			name: "xdg cache dir override",
			env:  map[string]string{"HOME": "/h", "XDG_CACHE_HOME": "/x"},
			check: func(t *testing.T, c Config) {
				want := filepath.Join("/x", AppName, "repos")
				if c.ReposDir != want {
					t.Errorf("got %q want %q", c.ReposDir, want)
				}
			},
		},
		{
			name:    "invalid mode rejected",
			argv:    []string{"--mode=garbage"},
			env:     map[string]string{"HOME": "/h"},
			wantErr: true,
		},
		{
			name: "valid mode pr",
			argv: []string{"--mode=pr"},
			env:  map[string]string{"HOME": "/h"},
			check: func(t *testing.T, c Config) {
				if c.Mode != ModePR {
					t.Error("mode")
				}
			},
		},
		{
			name: "GH_USER + COMMIT_MESSAGE captured",
			env:  map[string]string{"HOME": "/h", "GH_USER": "octocat", "COMMIT_MESSAGE": "docs: x"},
			check: func(t *testing.T, c Config) {
				if c.GHUser != "octocat" || c.CommitMessage != "docs: x" {
					t.Error("env capture")
				}
			},
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			cfg, err := Parse(tc.argv, envFromMap(tc.env), &bytes.Buffer{})
			if tc.wantErr {
				if err == nil {
					t.Fatal("want error")
				}
				return
			}
			if err != nil {
				t.Fatalf("err: %v", err)
			}
			if tc.check != nil {
				tc.check(t, cfg)
			}
		})
	}
}

func TestParseHelpReturnsErrUsage(t *testing.T) {
	_, err := Parse([]string{"--help"}, envFromMap(map[string]string{"HOME": "/h"}), &bytes.Buffer{})
	if !errors.Is(err, ErrUsage) {
		t.Fatalf("want ErrUsage, got %v", err)
	}
}

func TestXDGStateDir(t *testing.T) {
	got := XDGStateDir(envFromMap(map[string]string{"HOME": "/h"}))
	want := filepath.Join("/h", ".cache", AppName, "state")
	if got != want {
		t.Errorf("got %q want %q", got, want)
	}
	got2 := XDGStateDir(envFromMap(map[string]string{"HOME": "/h", "XDG_CACHE_HOME": "/c"}))
	want2 := filepath.Join("/c", AppName, "state")
	if got2 != want2 {
		t.Errorf("got %q want %q", got2, want2)
	}
}
