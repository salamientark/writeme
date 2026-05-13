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
	"time"

	"golang.org/x/term"

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
	"github.com/salamientark/writeme/internal/ui"
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

	// Convert repos for selection display.
	selRepos := convertToSelectionRepos(repos, contribByName)
	_ = contribByName

	if len(selRepos) == 0 {
		fmt.Fprintln(deps.Stdout, "Nothing selected.")
		return store.Summary()
	}

	stdinReader := bufio.NewReader(deps.Stdin)

	// Selection: TUI when available and not overridden.
	var pickedRepos []selection.Repo
	if !cfg.Plain && isTerminal(deps.Stdout) && isTerminalReader(deps.Stdin) {
		result := ui.RunSelection(selRepos)
		if result.Quit || len(result.Repos) == 0 {
			fmt.Fprintln(deps.Stdout, "Nothing selected.")
			sum, _ := store.Summary()
			return sum, nil
		}
		pickedRepos = result.Repos
	} else {
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
		// Map indices back to selection.Repo.
		for _, idx := range picked {
			pickedRepos = append(pickedRepos, selRepos[idx])
		}
	}

	// Build job list from selected repos.
	type job struct {
		repo selection.Repo
	}
	jobs := make([]job, 0, len(pickedRepos))
	for _, r := range pickedRepos {
		jobs = append(jobs, job{repo: r})
	}

	// Build a name → fetch.Repo map for clone URLs.
	repoByName := make(map[string]fetch.Repo, len(repos))
	for _, r := range repos {
		repoByName[r.Name] = r
	}

	type prepResult struct {
		Repo       selection.Repo
		Generation review.GenerationResult
		Err        error
	}

	sandboxBase := filepath.Join(cfg.ReposDir, ".sandbox")

	jobsCtx, jobsCancel := context.WithCancel(ctx)
	defer jobsCancel()
	resultsCh := worker.Run(jobsCtx, cfg.Parallel, jobs, func(jobCtx context.Context, j job) (prepResult, error) {
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
		gen, err := review.GenerateDraft(genCtx, deps.Runner, cfg.ReposDir, repoDir, env)
		return prepResult{Repo: j.repo, Generation: gen, Err: err}, nil
	})

	recordOrWarn := func(name, status string, opts state.RecordOpts) {
		if err := store.Record(name, status, opts); err != nil {
			fmt.Fprintf(deps.Stderr, "WARN: state record failed for %s: %v\n", name, err)
		}
	}

	basePrompter := review.NewStdinPrompter(stdinReader, deps.Stdout)
	useTUI := !cfg.Plain && isTerminal(deps.Stdout) && isTerminalReader(deps.Stdin)
	cleaner := func(c context.Context, dir string) error { return safety.EnsureClean(c, dir) }

	// Single consumer: review FSM + ship action per result.
	totalRepos := len(pickedRepos)
	repoIdx := 0
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
		repoIdx++
		repoDir := filepath.Join(cfg.ReposDir, pr.Repo.Name)

		// Render diff before prompting (FSM does not echo it itself).
		if pr.Generation.Status == review.StatusReady {
			text, derr := diff.Plain(ctx, repoDir)
			if derr != nil {
				fmt.Fprintf(deps.Stderr, "WARN %s: render diff failed: %v\n", pr.Repo.Name, derr)
			} else {
				fmt.Fprintf(deps.Stdout, "\n=== %s ===\n%s\n", pr.Repo.Name, text)
			}
		}

		gen := pr.Generation
		regen := func(gCtx context.Context, prev string) (review.GenerationResult, error) {
			jobSandbox, sbErr := sandbox.JobSandbox(filepath.Join(cfg.ReposDir, ".sandbox"), pr.Repo.Name)
			if sbErr != nil {
				return review.GenerationResult{}, sbErr
			}
			defer jobSandbox.Cleanup()
			env := review.ScrubEnv(deps.Env, sandbox.EnvFor(jobSandbox))
			rgCtx := gCtx
			if cfg.ClaudeTimeout > 0 {
				var cancel context.CancelFunc
				rgCtx, cancel = context.WithTimeout(gCtx, time.Duration(cfg.ClaudeTimeout)*time.Second)
				defer cancel()
			}
			out, err := review.GenerateDraft(rgCtx, deps.Runner, cfg.ReposDir, repoDir, env)
			out.PrevDraft = prev
			return out, err
		}

		// Choose prompter: TUI for accept screen when available.
		var loopPrompter review.Prompter = basePrompter
		if useTUI && gen.Status == review.StatusReady {
			loopPrompter = NewTUIPrompter(basePrompter, pr.Repo.Name, repoIdx, totalRepos)
		}

		res := review.Loop(ctx, review.SessionConfig{
			RepoDir:         repoDir,
			RepoName:        pr.Repo.Name,
			HadReadmeBefore: pr.Repo.HadReadmeBefore,
			Pregenerated:    &gen,
			Generator:       regen,
			Prompter:        loopPrompter,
			Cleaner:         cleaner,
		})

		switch res.Decision {
		case review.DecisionQuit:
			recordOrWarn(pr.Repo.Name, state.StatusSkipped, state.RecordOpts{Error: res.Reason})
			jobsCancel()
			for range resultsCh {
				// drain to let producers exit cleanly
			}
			goto done
		case review.DecisionFailed:
			recordOrWarn(pr.Repo.Name, state.StatusFailed, state.RecordOpts{Error: res.Reason})
			fmt.Fprintf(deps.Stderr, "FAILED %s: %s\n", pr.Repo.Name, res.Reason)
			continue
		case review.DecisionSkipped:
			recordOrWarn(pr.Repo.Name, state.StatusSkipped, state.RecordOpts{Error: res.Reason})
			continue
		case review.DecisionAccepted:
			// fall through to ship
		}

		mode := commit.Mode(cfg.Mode)
		if mode == "" {
			mode = commit.PromptMode(ctx, stdinReader, deps.Stdout)
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
done:

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

// convertToSelectionRepos converts fetch.Repo to selection.Repo, attaching contributor data.
func convertToSelectionRepos(repos []fetch.Repo, contribByName map[string][]string) []selection.Repo {
	out := make([]selection.Repo, len(repos))
	for i, r := range repos {
		out[i] = selection.Repo{
			Name:            r.Name,
			SSHURL:          r.SSHURL,
			PushedAt:        r.PushedAt,
			HadReadmeBefore: r.HadReadmeBefore,
			DiskUsage:       r.DiskUsage,
			IsFork:          r.IsFork,
			Contributors:    contribByName[r.Name],
		}
	}
	return out
}

// isTerminal reports whether w is a terminal.
func isTerminal(w io.Writer) bool {
	f, ok := w.(*os.File)
	if !ok {
		return false
	}
	return term.IsTerminal(int(f.Fd()))
}

// isTerminalReader reports whether r is a terminal.
func isTerminalReader(r io.Reader) bool {
	f, ok := r.(*os.File)
	if !ok {
		return false
	}
	return term.IsTerminal(int(f.Fd()))
}
