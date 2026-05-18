// Package cli parses flags + environment for writeme.
package cli

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
)

const (
	DefaultParallel = 3
	DefaultTimeout  = 300
	HardLimit       = 1000
	DefaultLimit    = 500
	ParallelCap     = 8
	AppName         = "gh-readme-pipeline"
)

type Mode string

const (
	ModeUnset      Mode = ""
	ModePR         Mode = "pr"
	ModeDirect     Mode = "direct"
	ModeCommitOnly Mode = "commit-only"
)

type Config struct {
	Mode          Mode
	DryRun        bool
	ReposDir      string
	ClaudeTimeout int
	Resume        bool
	Clean         bool
	SkipCI        bool
	Parallel      int
	Plain         bool
	Limit         int
	GHUser        string
	CommitMessage string
	Version       bool
}

type Env func(key string) (string, bool)

func OSEnv(key string) (string, bool) { return os.LookupEnv(key) }

var ErrUsage = errors.New("usage requested")

func Parse(argv []string, env Env, stderr io.Writer) (Config, error) {
	if env == nil {
		env = OSEnv
	}
	fs := flag.NewFlagSet(AppName, flag.ContinueOnError)
	fs.SetOutput(stderr)

	const sentinelInt = -1
	var (
		modeFlag     string
		reposDirFlag string
		timeoutFlag  int
		parallelFlag int
		cfg          Config
	)

	fs.StringVar(&modeFlag, "mode", "", "Push mode: pr|direct|commit-only")
	fs.BoolVar(&cfg.DryRun, "dry-run", false, "Run full loop but never push.")
	fs.StringVar(&reposDirFlag, "repos-dir", "", "Override clone cache directory.")
	fs.IntVar(&timeoutFlag, "claude-timeout", sentinelInt, "Claude subprocess timeout in seconds.")
	fs.BoolVar(&cfg.Resume, "resume", false, "Skip already-processed repos.")
	fs.BoolVar(&cfg.Clean, "clean", false, "Remove cache dir and exit 0.")
	fs.BoolVar(&cfg.SkipCI, "skip-ci", false, "Append [skip ci] to commit message.")
	fs.IntVar(&parallelFlag, "parallel", sentinelInt, "Parallel claude workers (1-8).")
	fs.BoolVar(&cfg.Plain, "plain", false, "Disable Rich UI.")
	fs.BoolVar(&cfg.Version, "version", false, "Print version and exit.")

	if err := fs.Parse(argv); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return Config{}, ErrUsage
		}
		return Config{}, err
	}

	skipCIFlagSet := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "skip-ci" {
			skipCIFlagSet = true
		}
	})

	switch Mode(modeFlag) {
	case ModeUnset, ModePR, ModeDirect, ModeCommitOnly:
		cfg.Mode = Mode(modeFlag)
	default:
		return Config{}, fmt.Errorf("invalid --mode: %q", modeFlag)
	}

	if reposDirFlag != "" {
		cfg.ReposDir = reposDirFlag
	} else if v, ok := env("GH_README_REPOS_DIR"); ok && v != "" {
		cfg.ReposDir = v
	} else {
		cfg.ReposDir = filepath.Join(XDGCacheDir(env), "repos")
	}

	switch {
	case timeoutFlag != sentinelInt:
		cfg.ClaudeTimeout = timeoutFlag
	default:
		cfg.ClaudeTimeout = DefaultTimeout
		if v, ok := env("CLAUDE_TIMEOUT"); ok && v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				cfg.ClaudeTimeout = n
			}
		}
	}

	if !skipCIFlagSet {
		if v, ok := env("SKIP_CI"); ok && v != "" {
			cfg.SkipCI = true
		}
	}

	switch {
	case parallelFlag != sentinelInt:
		cfg.Parallel = parallelFlag
	default:
		cfg.Parallel = DefaultParallel
		if v, ok := env("WRITEME_PARALLEL"); ok && v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				cfg.Parallel = n
			}
		}
	}
	if cfg.Parallel < 1 {
		cfg.Parallel = 1
	}
	if cfg.Parallel > ParallelCap {
		cfg.Parallel = ParallelCap
	}

	cfg.Limit = DefaultLimit
	if v, ok := env("LIMIT"); ok && v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			if n > HardLimit {
				n = HardLimit
			}
			cfg.Limit = n
		}
	}

	if v, ok := env("GH_USER"); ok {
		cfg.GHUser = v
	}
	if v, ok := env("COMMIT_MESSAGE"); ok {
		cfg.CommitMessage = v
	}

	return cfg, nil
}

func XDGCacheDir(env Env) string {
	if env == nil {
		env = OSEnv
	}
	if v, ok := env("XDG_CACHE_HOME"); ok && v != "" {
		return filepath.Join(v, AppName)
	}
	home, _ := env("HOME")
	return filepath.Join(home, ".cache", AppName)
}

// XDGStateDir returns the state directory. Historically this lived under
// $XDG_STATE_HOME, but writeme consolidates everything under the cache root so
// `--clean` wipes state along with cloned repos.
func XDGStateDir(env Env) string {
	return filepath.Join(XDGCacheDir(env), "state")
}
