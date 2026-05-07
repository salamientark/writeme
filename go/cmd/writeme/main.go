package main

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/salamientark/writeme/internal/cli"
	"github.com/salamientark/writeme/internal/commit"
	"github.com/salamientark/writeme/internal/contributors"
	"github.com/salamientark/writeme/internal/fetch"
	"github.com/salamientark/writeme/internal/pipeline"
	"github.com/salamientark/writeme/internal/review"
	"github.com/salamientark/writeme/internal/safety"
	"github.com/salamientark/writeme/internal/state"
)

func main() {
	os.Exit(run())
}

func run() int {
	cfg, err := cli.Parse(os.Args[1:], cli.OSEnv, os.Stderr)
	if errors.Is(err, cli.ErrUsage) {
		return 0
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}

	if cfg.Clean {
		fmt.Fprintf(os.Stderr, "Removing %s\n", cfg.ReposDir)
		_ = os.RemoveAll(cfg.ReposDir)
		return 0
	}

	user, err := resolveUser(cfg.GHUser, os.Stdin, os.Stderr)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}

	stateDir := cli.XDGStateDir(cli.OSEnv)
	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "mkdir state: %v\n", err)
		return 1
	}

	store, err := state.New(user, stateDir, state.RealClock())
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}

	release, err := safety.AcquireLock(filepath.Join(stateDir, "lock"))
	if err != nil {
		fmt.Fprintln(os.Stderr, "Another writeme instance is running.")
		return 1
	}
	defer release()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	commit.WarnGPGSigning(ctx, ".", os.Stderr)

	deps := pipeline.Deps{
		Fetcher:      fetch.NewGHFetcher(os.Stderr),
		ContribFetch: contributors.ShellFetch,
		Runner:       review.ShellRunner{},
		Stdin:        os.Stdin,
		Stdout:       os.Stdout,
		Stderr:       os.Stderr,
		User:         user,
		StateDir:     stateDir,
	}
	_, runErr := pipeline.Run(ctx, cfg, store, deps)
	if errors.Is(ctx.Err(), context.Canceled) {
		fmt.Fprintln(os.Stderr, "Interrupted. Flushing state...")
		printSummary(store)
		return 130
	}
	printSummary(store)
	if runErr != nil {
		if errors.Is(runErr, pipeline.ErrUnpushedDirty) {
			return 2
		}
		return 1
	}
	return 0
}

// resolveUser determines the GitHub user, querying `gh api user` when available
// and prompting on mismatch with GH_USER. Mirrors Python _resolve_user.
func resolveUser(envUser string, stdin *os.File, stderr *os.File) (string, error) {
	ghLogin, ghErr := ghAPIUser()
	switch {
	case ghErr == nil && envUser == "":
		return ghLogin, nil
	case ghErr == nil && envUser == ghLogin:
		return ghLogin, nil
	case ghErr == nil && envUser != ghLogin:
		fmt.Fprintf(stderr, "GH_USER=%q but `gh auth` user is %q. Use %q? [y/N] ", envUser, ghLogin, ghLogin)
		r := bufio.NewReader(stdin)
		line, _ := r.ReadString('\n')
		if strings.EqualFold(strings.TrimSpace(line), "y") {
			return ghLogin, nil
		}
		return envUser, nil
	case envUser != "":
		return envUser, nil
	default:
		return "", fmt.Errorf("could not determine GitHub user. Set GH_USER or run 'gh auth login'")
	}
}

func ghAPIUser() (string, error) {
	out, err := exec.Command("gh", "api", "user", "--jq", ".login").Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

func printSummary(store *state.Store) {
	sum, err := store.Summary()
	if err != nil {
		return
	}
	pipeline.PrintSummary(os.Stdout, sum)
}
