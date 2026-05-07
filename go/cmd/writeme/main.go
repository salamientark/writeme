package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/salamientark/writeme/internal/cli"
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
		if cfg.ReposDir == "" {
			return 0
		}
		fmt.Fprintf(os.Stderr, "Removing %s\n", cfg.ReposDir)
		_ = os.RemoveAll(cfg.ReposDir)
		return 0
	}

	user := cfg.GHUser
	if user == "" {
		fmt.Fprintln(os.Stderr, "ERROR: could not determine GitHub user. Set GH_USER or run 'gh auth login'.")
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

	release, err := safety.AcquireLock(stateDir + "/lock")
	if err != nil {
		fmt.Fprintln(os.Stderr, "Another writeme instance is running.")
		return 1
	}
	defer release()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

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

func printSummary(store *state.Store) {
	sum, err := store.Summary()
	if err != nil {
		return
	}
	fmt.Println("--- Summary ---")
	for _, k := range []struct {
		label  string
		status string
	}{
		{"Pushed (PR)", state.StatusPROpened},
		{"Pushed (direct)", state.StatusPushed},
		{"Commit only", state.StatusCommitOnly},
		{"Skipped", state.StatusSkipped},
		{"Failed", state.StatusFailed},
	} {
		fmt.Printf("  %-20s %d\n", k.label, sum.Counts[k.status])
	}
	if len(sum.PRURLs) > 0 {
		fmt.Println()
		fmt.Println("PR URLs:")
		for _, u := range sum.PRURLs {
			fmt.Printf("  %s\n", u)
		}
	}
	if len(sum.FailedRepos) > 0 {
		fmt.Println()
		fmt.Println("Failed repos:")
		for _, r := range sum.FailedRepos {
			fmt.Printf("  %s\n", r)
		}
	}
}
