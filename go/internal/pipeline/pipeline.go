// Package pipeline orchestrates the end-to-end writeme run.
package pipeline

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/salamientark/writeme/internal/cli"
	"github.com/salamientark/writeme/internal/commit"
	"github.com/salamientark/writeme/internal/contributors"
	"github.com/salamientark/writeme/internal/diff"
	"github.com/salamientark/writeme/internal/fetch"
	"github.com/salamientark/writeme/internal/review"
	"github.com/salamientark/writeme/internal/safety"
	"github.com/salamientark/writeme/internal/sandbox"
	"github.com/salamientark/writeme/internal/selection"
	"github.com/salamientark/writeme/internal/state"
	"github.com/salamientark/writeme/internal/unpushed"
	"github.com/salamientark/writeme/internal/worker"
)

// Deps bundles all collaborators so tests can inject fakes.
type Deps struct {
	Fetcher        fetch.Fetcher
	ContribFetch   contributors.FetchFunc
	Runner         review.Runner
	Stdin          io.Reader
	Stdout         io.Writer
	Stderr         io.Writer
	User           string
	StateDir       string
	ContribWorkers int
	Env            []string // nil → os.Environ()
}

// ErrUnpushedDirty signals exit code 2 (unpushed/dirty work in repos cache).
var ErrUnpushedDirty = errors.New("unpushed or dirty work present")

// Run executes the full pipeline.
func Run(ctx context.Context, cfg cli.Config, store *state.Store, deps Deps) (state.Summary, error) {
	if store == nil {
		return state.Summary{}, errors.New("nil store")
	}
	if deps.Stdout == nil {
		deps.Stdout = os.Stdout
	}
	if deps.Stderr == nil {
		deps.Stderr = os.Stderr
	}
	if deps.Stdin == nil {
		deps.Stdin = os.Stdin
	}
	if deps.Env == nil {
		deps.Env = os.Environ()
	}

	if err := os.MkdirAll(cfg.ReposDir, 0o755); err != nil {
		return state.Summary{}, fmt.Errorf("mkdir repos: %w", err)
	}

	repos, err := deps.Fetcher.ListRepos(ctx, deps.User, cfg.Limit)
	if err != nil {
		return state.Summary{}, fmt.Errorf("list repos: %w", err)
	}

	// Contributor enrichment (parallel).
	cachePath := filepath.Join(cfg.ReposDir, ".contributors.json")
	enrichInput := make([]contributors.Repo, len(repos))
	for i, r := range repos {
		enrichInput[i] = contributors.Repo{Name: r.Name, PushedAt: r.PushedAt}
	}
	workers := deps.ContribWorkers
	if workers <= 0 {
		workers = 4
	}
	enriched, err := contributors.Enrich(ctx, deps.User, enrichInput, cachePath, deps.ContribFetch, workers)
	if err != nil {
		return state.Summary{}, fmt.Errorf("enrich contributors: %w", err)
	}
	contribByName := make(map[string][]string, len(enriched))
	for _, r := range enriched {
		contribByName[r.Repo.Name] = r.Contributors
	}

	// Apply resume semantics.
	if cfg.Resume && store.HasPriorState() {
		processed, err := store.LoadProcessed()
		if err != nil {
			return state.Summary{}, err
		}
		choice, err := state.PromptResume(deps.Stdin, deps.Stdout, len(processed))
		if err != nil {
			return state.Summary{}, err
		}
		switch choice {
		case state.ResumeQuit:
			sum, _ := store.Summary()
			return sum, nil
		case state.ResumeKeep:
			repos = filterOutProcessed(repos, processed)
		case state.ResumeAll, state.ResumeFresh:
			// no-op (process everything; fresh just means re-run)
		}
	}

	// TODO(phase4): wire filters into selection display via convertForFilters.
	_ = contribByName

	if len(repos) == 0 {
		fmt.Fprintln(deps.Stdout, "Nothing selected.")
		return store.Summary()
	}

	stdinReader := bufio.NewReader(deps.Stdin)
	selection.RenderPlain(deps.Stdout, repos)
	picked, err := selection.Prompt(stdinReader, deps.Stdout, len(repos))
	if err != nil {
		return state.Summary{}, err
	}
	if len(picked) == 0 {
		fmt.Fprintln(deps.Stdout, "Nothing selected.")
		sum, _ := store.Summary()
		return sum, nil
	}

	// Build job list.
	type job struct {
		repo fetch.Repo
	}
	jobs := make([]job, 0, len(picked))
	for _, idx := range picked {
		jobs = append(jobs, job{repo: repos[idx]})
	}

	type prepResult struct {
		Repo       fetch.Repo
		Generation review.GenerationResult
		Err        error
	}

	sandboxBase := filepath.Join(cfg.ReposDir, ".sandbox")

	resultsCh := worker.Run(ctx, cfg.Parallel, jobs, func(jobCtx context.Context, j job) (prepResult, error) {
		repoDir := filepath.Join(cfg.ReposDir, j.repo.Name)
		if err := commit.CloneOrFetch(jobCtx, j.repo.SSHURL, repoDir); err != nil {
			return prepResult{Repo: j.repo, Err: fmt.Errorf("clone: %w", err)}, nil
		}
		if err := safety.EnsureClean(jobCtx, repoDir); err != nil {
			return prepResult{Repo: j.repo, Err: err}, nil
		}
		jobSandbox, err := sandbox.JobSandbox(sandboxBase, j.repo.Name)
		if err != nil {
			return prepResult{Repo: j.repo, Err: err}, nil
		}
		defer jobSandbox.Cleanup()
		env := review.ScrubEnv(deps.Env, sandbox.EnvFor(jobSandbox))
		genCtx := jobCtx
		if cfg.ClaudeTimeout > 0 {
			var cancel context.CancelFunc
			genCtx, cancel = context.WithTimeout(jobCtx, time.Duration(cfg.ClaudeTimeout)*time.Second)
			defer cancel()
		}
		gen, err := review.GenerateDraft(genCtx, deps.Runner, repoDir, env)
		return prepResult{Repo: j.repo, Generation: gen, Err: err}, nil
	})

	recordOrWarn := func(name, status string, opts state.RecordOpts) {
		if err := store.Record(name, status, opts); err != nil {
			fmt.Fprintf(deps.Stderr, "WARN: state record failed for %s: %v\n", name, err)
		}
	}

	// Single consumer: review prompt + ship action per result.
	for r := range resultsCh {
		pr := r.Value
		if r.Err != nil {
			fmt.Fprintf(deps.Stderr, "ERROR %s: %v\n", pr.Repo.Name, r.Err)
			recordOrWarn(pr.Repo.Name, state.StatusFailed, state.RecordOpts{Error: r.Err.Error()})
			continue
		}
		if pr.Err != nil {
			fmt.Fprintf(deps.Stderr, "ERROR %s: %v\n", pr.Repo.Name, pr.Err)
			recordOrWarn(pr.Repo.Name, state.StatusFailed, state.RecordOpts{Error: pr.Err.Error()})
			continue
		}
		gen := pr.Generation
		if gen.Status != review.StatusReady {
			errMsg := string(gen.Status)
			if gen.Error != "" {
				errMsg = string(gen.Status) + ": " + gen.Error
			}
			recordOrWarn(pr.Repo.Name, state.StatusFailed, state.RecordOpts{Error: errMsg})
			fmt.Fprintf(deps.Stderr, "FAILED %s: %s\n", pr.Repo.Name, errMsg)
			continue
		}
		repoDir := filepath.Join(cfg.ReposDir, pr.Repo.Name)
		if len(gen.SecretMatches) > 0 {
			fmt.Fprintf(deps.Stderr, "BLOCKED %s: secrets in generated README (%d match(es))\n", pr.Repo.Name, len(gen.SecretMatches))
			recordOrWarn(pr.Repo.Name, state.StatusFailed, state.RecordOpts{Error: "secret_in_generated_content"})
			_ = safety.EnsureClean(ctx, repoDir)
			continue
		}
		// Render diff + prompt.
		text, _ := diff.Plain(ctx, repoDir)
		fmt.Fprintf(deps.Stdout, "\n=== %s ===\n%s\n", pr.Repo.Name, text)
		choice := promptReview(stdinReader, deps.Stdout)
		if choice == "q" {
			recordOrWarn(pr.Repo.Name, state.StatusSkipped, state.RecordOpts{Error: "user_quit"})
			break
		}
		if choice == "d" {
			recordOrWarn(pr.Repo.Name, state.StatusSkipped, state.RecordOpts{})
			_ = safety.EnsureClean(ctx, repoDir)
			continue
		}
		if choice == "r" {
			recordOrWarn(pr.Repo.Name, state.StatusSkipped, state.RecordOpts{Error: "redo_unsupported_v1"})
			_ = safety.EnsureClean(ctx, repoDir)
			continue
		}
		// accept → ship
		mode := commit.Mode(cfg.Mode)
		if mode == "" {
			mode = promptMode(stdinReader, deps.Stdout)
		}
		out := commit.CommitAndPush(ctx, repoDir, commit.Options{
			Mode:                  mode,
			HadReadmeBefore:       pr.Repo.HadReadmeBefore,
			DryRun:                cfg.DryRun,
			SkipCI:                cfg.SkipCI,
			CommitMessageOverride: cfg.CommitMessage,
		})
		opts := state.RecordOpts{Mode: out.Mode, PRURL: out.PRURL, Error: out.Error}
		recordOrWarn(pr.Repo.Name, out.Status, opts)
	}

	// Final unpushed scan.
	findings, err := unpushed.Scan(ctx, cfg.ReposDir)
	if err == nil && len(findings) > 0 {
		fmt.Fprintln(deps.Stderr, "Unpushed/dirty work detected:")
		for _, f := range findings {
			fmt.Fprintf(deps.Stderr, "  %s: dirty=%v, %d unpushed commit(s)\n", f.Path, f.Dirty, f.UnpushedCommits)
		}
		sum, _ := store.Summary()
		return sum, ErrUnpushedDirty
	}
	return store.Summary()
}

func filterOutProcessed(repos []fetch.Repo, processed map[string]state.Record) []fetch.Repo {
	out := make([]fetch.Repo, 0, len(repos))
	for _, r := range repos {
		if _, ok := processed[r.Name]; !ok {
			out = append(out, r)
		}
	}
	return out
}

func promptReview(r *bufio.Reader, w io.Writer) string {
	for {
		fmt.Fprint(w, "[a]ccept / [r]edo / [d]iscard / [q]uit: ")
		line, err := r.ReadString('\n')
		if err != nil && line == "" {
			return "q"
		}
		s := strings.ToLower(strings.TrimSpace(line))
		switch s {
		case "a", "r", "d", "q":
			return s
		}
	}
}

func promptMode(r *bufio.Reader, w io.Writer) commit.Mode {
	for {
		fmt.Fprint(w, "Mode? [p]r / [m]ain (direct) / [c]ommit-only / [n]o: ")
		line, err := r.ReadString('\n')
		if err != nil && line == "" {
			return commit.ModeSkip
		}
		switch strings.ToLower(strings.TrimSpace(line)) {
		case "p":
			return commit.ModePR
		case "m":
			return commit.ModeDirect
		case "c":
			return commit.ModeCommitOnly
		case "n":
			return commit.ModeSkip
		}
	}
}
