package pipeline

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/salamientark/writeme/internal/cli"
	"github.com/salamientark/writeme/internal/contributors"
	"github.com/salamientark/writeme/internal/fetch"
	"github.com/salamientark/writeme/internal/review"
	"github.com/salamientark/writeme/internal/state"
	"github.com/salamientark/writeme/internal/ui"
)

// fakeFetcher serves a fixed list.
type fakeFetcher struct{ repos []fetch.Repo }

func (f *fakeFetcher) ListRepos(ctx context.Context, user string, limit int) ([]fetch.Repo, error) {
	return f.repos, nil
}

// fakeRunner writes a deterministic README.md inside repoDir.
type fakeRunner struct {
	body string
	fail bool
}

func (f *fakeRunner) Run(ctx context.Context, repoDir string, env []string) (int, string, error) {
	if f.fail {
		return 1, "", nil
	}
	if err := os.WriteFile(filepath.Join(repoDir, "README.md"), []byte(f.body), 0o644); err != nil {
		return 1, "", err
	}
	return 0, "", nil
}

func setupBareRemote(t *testing.T, name string) string {
	t.Helper()
	bare := filepath.Join(t.TempDir(), name+".git")
	c := exec.Command("git", "init", "--bare", "-q", "-b", "main", bare)
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("init bare: %v %s", err, out)
	}
	// Seed with one commit so clone --depth=1 works.
	tmp := filepath.Join(t.TempDir(), "seed-"+name)
	for _, args := range [][]string{
		{"git", "clone", "-q", bare, tmp},
		{"git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", "-q"},
		{"git", "-C", tmp, "push", "-u", "origin", "main", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("%v: %v %s", args, err, out)
		}
	}
	return bare
}

func TestPipelineDirectDryRun(t *testing.T) {
	bare := setupBareRemote(t, "demo")
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")

	store, err := state.New("testuser", stateDir, state.FixedClock(time.Unix(1700000000, 0).UTC()))
	if err != nil {
		t.Fatal(err)
	}
	cfg := cli.Config{
		Mode:     cli.ModeDirect,
		DryRun:   true,
		Parallel: 1,
		Limit:    10,
		ReposDir: reposDir,
	}
	deps := Deps{
		Fetcher: &fakeFetcher{repos: []fetch.Repo{
			{Name: "demo", SSHURL: "https://github.com/o/r"},
		}},
		ContribFetch: func(ctx context.Context, owner, name string) ([]string, error) { return []string{"alice"}, nil },
		Runner:       &fakeRunner{body: "# generated\n"},
		User:         "testuser",
		StateDir:     stateDir,
		Stdin:        strings.NewReader("a\na\n"), // select all + accept
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	// Override SSH URL to local bare so clone works.
	deps.Fetcher = &fakeFetcher{repos: []fetch.Repo{{Name: "demo", SSHURL: bare}}}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	sum, err := Run(context.Background(), cfg, store, deps)
	// Dry-run leaves an unpushed commit → ErrUnpushedDirty is expected.
	if err != nil && err != ErrUnpushedDirty {
		t.Fatalf("run: %v", err)
	}
	if sum.Counts[state.StatusPushed] != 1 {
		t.Errorf("expected 1 pushed (dry-run direct), got %+v", sum.Counts)
	}
}

// Ensure the validator doesn't reject our local bare path. Using https://github.com/o/r
// would fail safety.ValidateSSHURL during decode, but the Fetcher is faked so we bypass that.
var _ = contributors.IsBot
var _ = review.StatusReady

func TestPipelineNothingSelected(t *testing.T) {
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir}
	var stdout bytes.Buffer
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "x", SSHURL: "https://github.com/o/r"}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{},
		User:         "u",
		Stdin:        strings.NewReader("\n"), // empty → quit
		Stdout:       &stdout,
		Stderr:       &bytes.Buffer{},
	}
	if _, err := Run(context.Background(), cfg, store, deps); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(stdout.String(), "Nothing selected") {
		t.Errorf("missing message: %q", stdout.String())
	}
}

func TestFilterOutProcessed(t *testing.T) {
	in := []fetch.Repo{{Name: "a"}, {Name: "b"}, {Name: "c"}}
	processed := map[string]state.Record{"b": {}}
	out := filterOutProcessed(in, processed)
	if len(out) != 2 || out[0].Name != "a" || out[1].Name != "c" {
		t.Errorf("got %v", out)
	}
}

func TestPipelineModePrompt(t *testing.T) {
	bare := setupBareRemote(t, "demo2")
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, DryRun: true}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "demo2", SSHURL: bare}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{body: "x\n"},
		User:         "u",
		// select all → accept → mode=c (commit-only)
		Stdin:  strings.NewReader("a\na\nc\n"),
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	sum, _ := Run(context.Background(), cfg, store, deps)
	if sum.Counts[state.StatusCommitOnly] != 1 {
		t.Errorf("got %+v", sum.Counts)
	}
}

func TestPipelineFailedGeneration(t *testing.T) {
	// Per Python parity: nonzero → prompt → [d]iscard → skipped (claude_nonzero_exit).
	bare := setupBareRemote(t, "demo3")
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, Mode: cli.ModeCommitOnly}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "demo3", SSHURL: bare}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{fail: true}, // claude returns nonzero
		User:         "u",
		Stdin:        strings.NewReader("a\nd\n"),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	sum, _ := Run(context.Background(), cfg, store, deps)
	if sum.Counts[state.StatusSkipped] != 1 {
		t.Errorf("got %+v", sum.Counts)
	}
}

func TestPipelineDiscard(t *testing.T) {
	bare := setupBareRemote(t, "demo4")
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, Mode: cli.ModeCommitOnly}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "demo4", SSHURL: bare}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{body: "x\n"},
		User:         "u",
		Stdin:        strings.NewReader("a\nd\n"), // accept all → discard
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	sum, _ := Run(context.Background(), cfg, store, deps)
	if sum.Counts[state.StatusSkipped] != 1 {
		t.Errorf("got %+v", sum.Counts)
	}
}

func TestPipelineResume(t *testing.T) {
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	// Pre-record a processed repo.
	_ = store.Record("done", state.StatusPushed, state.RecordOpts{Mode: "direct"})
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, Resume: true}
	deps := Deps{
		Fetcher: &fakeFetcher{repos: []fetch.Repo{
			{Name: "done", SSHURL: "https://github.com/o/r"},
		}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{},
		User:         "u",
		// resume choice = q (quit)
		Stdin:  strings.NewReader("q\n"),
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}
	if _, err := Run(context.Background(), cfg, store, deps); err != nil {
		t.Fatal(err)
	}
}

// promptMode/promptReview tests moved to internal/commit and internal/review.

func TestPipelineNilStore(t *testing.T) {
	_, err := Run(context.Background(), cli.Config{}, nil, Deps{})
	if err == nil {
		t.Fatal("want err")
	}
}

type errFetcher struct{}

func (errFetcher) ListRepos(ctx context.Context, user string, limit int) ([]fetch.Repo, error) {
	return nil, context.DeadlineExceeded
}

func TestPipelineListReposErr(t *testing.T) {
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir}
	deps := Deps{
		Fetcher:      errFetcher{},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{},
		User:         "u",
		Stdin:        strings.NewReader(""),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	if _, err := Run(context.Background(), cfg, store, deps); err == nil {
		t.Fatal("want err")
	}
}

func TestPipelineEnrichErr(t *testing.T) {
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "x", PushedAt: "p"}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, context.DeadlineExceeded },
		Runner:       &fakeRunner{},
		User:         "u",
		Stdin:        strings.NewReader(""),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	if _, err := Run(context.Background(), cfg, store, deps); err == nil {
		t.Fatal("want err")
	}
}

func TestPipelineMkdirError(t *testing.T) {
	tmp := t.TempDir()
	blocker := filepath.Join(tmp, "blocker")
	_ = os.WriteFile(blocker, []byte("x"), 0o644)
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: filepath.Join(blocker, "sub")}
	deps := Deps{
		Fetcher:      &fakeFetcher{},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{},
		User:         "u",
		Stdin:        strings.NewReader(""),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	if _, err := Run(context.Background(), cfg, store, deps); err == nil {
		t.Fatal("want err")
	}
}

func TestPipelineQuit(t *testing.T) {
	bare := setupBareRemote(t, "demoq")
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, Mode: cli.ModeCommitOnly}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "demoq", SSHURL: bare}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{body: "x\n"},
		User:         "u",
		Stdin:        strings.NewReader("a\nq\n"),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	sum, _ := Run(context.Background(), cfg, store, deps)
	if sum.Counts[state.StatusSkipped] != 1 {
		t.Errorf("got %+v", sum.Counts)
	}
}

func TestPipelineRedo(t *testing.T) {
	bare := setupBareRemote(t, "demor")
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, Mode: cli.ModeCommitOnly}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "demor", SSHURL: bare}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{body: "x\n"},
		User:         "u",
		Stdin:        strings.NewReader("a\nr\n"),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	sum, _ := Run(context.Background(), cfg, store, deps)
	if sum.Counts[state.StatusSkipped] != 1 {
		t.Errorf("got %+v", sum.Counts)
	}
}

func TestPipelineCloneError(t *testing.T) {
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir, Mode: cli.ModeCommitOnly}
	deps := Deps{
		Fetcher:      &fakeFetcher{repos: []fetch.Repo{{Name: "nope", SSHURL: filepath.Join(t.TempDir(), "does-not-exist.git")}}},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{},
		User:         "u",
		Stdin:        strings.NewReader("a\n"),
		Stdout:       &bytes.Buffer{},
		Stderr:       &bytes.Buffer{},
	}
	sum, _ := Run(context.Background(), cfg, store, deps)
	if sum.Counts[state.StatusFailed] != 1 {
		t.Errorf("got %+v", sum.Counts)
	}
}

// fakePrompterForTUI is a minimal Prompter for testing tuiPrompter delegation.
type fakePrompterForTUI struct {
	riskyRet   string
	timeoutRet string
	nonzeroRet string
	secretRet  bool
	acceptRet  string

	riskyCalled   bool
	timeoutCalled bool
	nonzeroCalled bool
	secretCalled  bool
	acceptCalled  bool
}

func (f *fakePrompterForTUI) Accept(ctx context.Context, hadReadme bool, old, newC string) (string, error) {
	f.acceptCalled = true
	return f.acceptRet, nil
}

func (f *fakePrompterForTUI) RiskyFiles(ctx context.Context, risky []string) (string, error) {
	f.riskyCalled = true
	return f.riskyRet, nil
}
func (f *fakePrompterForTUI) Timeout(ctx context.Context) (string, error) {
	f.timeoutCalled = true
	return f.timeoutRet, nil
}
func (f *fakePrompterForTUI) Nonzero(ctx context.Context) (string, error) {
	f.nonzeroCalled = true
	return f.nonzeroRet, nil
}
func (f *fakePrompterForTUI) SecretOverride(ctx context.Context, matches []string) (bool, error) {
	f.secretCalled = true
	return f.secretRet, nil
}
func TestNewTUIPrompter(t *testing.T) {
	inner := &fakePrompterForTUI{}
	p := NewTUIPrompter(inner, "my-repo", 3, 10)
	tp, ok := p.(*tuiPrompter)
	if !ok {
		t.Fatal("NewTUIPrompter should return *tuiPrompter")
	}
	if tp.repoName != "my-repo" {
		t.Errorf("repoName = %q", tp.repoName)
	}
	if tp.index != 3 {
		t.Errorf("index = %d", tp.index)
	}
	if tp.total != 10 {
		t.Errorf("total = %d", tp.total)
	}
}

func TestTUIPrompterRiskyFiles(t *testing.T) {
	inner := &fakePrompterForTUI{riskyRet: "c"}
	p := NewTUIPrompter(inner, "r", 0, 0)
	v, err := p.RiskyFiles(context.Background(), []string{"file.go"})
	if err != nil {
		t.Fatal(err)
	}
	if v != "c" {
		t.Errorf("RiskyFiles = %q, want 'c'", v)
	}
	if !inner.riskyCalled {
		t.Error("inner.RiskyFiles was not called")
	}
}

func TestTUIPrompterTimeout(t *testing.T) {
	inner := &fakePrompterForTUI{timeoutRet: "s"}
	p := NewTUIPrompter(inner, "r", 0, 0)
	v, err := p.Timeout(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if v != "s" {
		t.Errorf("Timeout = %q, want 's'", v)
	}
	if !inner.timeoutCalled {
		t.Error("inner.Timeout was not called")
	}
}

func TestTUIPrompterNonzero(t *testing.T) {
	inner := &fakePrompterForTUI{nonzeroRet: "d"}
	p := NewTUIPrompter(inner, "r", 0, 0)
	v, err := p.Nonzero(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if v != "d" {
		t.Errorf("Nonzero = %q, want 'd'", v)
	}
	if !inner.nonzeroCalled {
		t.Error("inner.Nonzero was not called")
	}
}

func TestTUIPrompterSecretOverride(t *testing.T) {
	inner := &fakePrompterForTUI{secretRet: true}
	p := NewTUIPrompter(inner, "r", 0, 0)
	v, err := p.SecretOverride(context.Background(), []string{"SECRET"})
	if err != nil {
		t.Fatal(err)
	}
	if !v {
		t.Error("SecretOverride = false, want true")
	}
	if !inner.secretCalled {
		t.Error("inner.SecretOverride was not called")
	}
}

func TestTUIPrompterAccept(t *testing.T) {
	inner := &fakePrompterForTUI{acceptRet: "a"}
	p := NewTUIPrompter(inner, "test-repo", 2, 7)
	tp := p.(*tuiPrompter)

	// Inject a fake review runner that returns each decision.
	tests := []struct {
		decision ui.ReviewDecision
		want     string
	}{
		{ui.ReviewAccept, "a"},
		{ui.ReviewRedo, "r"},
		{ui.ReviewDiscard, "d"},
		{ui.ReviewQuit, "q"},
		{ui.ReviewDecision("unknown"), "q"},
	}
	for _, tt := range tests {
		tp.runReview = func(ctx ui.ReviewContext) ui.ReviewDecision {
			if ctx.RepoName != "test-repo" {
				t.Errorf("RepoName = %q", ctx.RepoName)
			}
			if ctx.Index != 2 {
				t.Errorf("Index = %d", ctx.Index)
			}
			if ctx.Total != 7 {
				t.Errorf("Total = %d", ctx.Total)
			}
			if ctx.CurrentDraft != "new-readme" {
				t.Errorf("CurrentDraft = %q", ctx.CurrentDraft)
			}
			return tt.decision
		}
		got, err := tp.Accept(context.Background(), false, "", "new-readme")
		if err != nil {
			t.Fatalf("Accept(%s): %v", tt.decision, err)
		}
		if got != tt.want {
			t.Errorf("Accept() with decision=%s = %q, want %q", tt.decision, got, tt.want)
		}
	}
}

func TestTUIPrompterAcceptWithHeadReadme(t *testing.T) {
	inner := &fakePrompterForTUI{acceptRet: "a"}
	p := NewTUIPrompter(inner, "r", 0, 0)
	tp := p.(*tuiPrompter)

	tp.runReview = func(ctx ui.ReviewContext) ui.ReviewDecision {
		if ctx.HeadReadme == nil {
			t.Error("HeadReadme should not be nil when hadReadme=true")
		} else if *ctx.HeadReadme != "old-content" {
			t.Errorf("HeadReadme = %q", *ctx.HeadReadme)
		}
		return ui.ReviewAccept
	}
	got, err := tp.Accept(context.Background(), true, "old-content", "new-content")
	if err != nil {
		t.Fatal(err)
	}
	if got != "a" {
		t.Errorf("Accept = %q, want 'a'", got)
	}
}

func TestIsTerminalOnRealFile(t *testing.T) {
	// os.Stderr is always an *os.File. We cover the branch that calls term.IsTerminal.
	// In test runners this usually isn't a TTY, but we just care about code coverage.
	_ = isTerminal(os.Stderr)
}

func TestIsTerminalOnNonFile(t *testing.T) {
	// bytes.Buffer is not an *os.File, so isTerminal should return false.
	var buf bytes.Buffer
	if isTerminal(&buf) {
		t.Error("isTerminal on bytes.Buffer should return false")
	}
}

func TestPipelineEmptyRepoList(t *testing.T) {
	reposDir := filepath.Join(t.TempDir(), "repos")
	stateDir := filepath.Join(t.TempDir(), "state")
	store, _ := state.New("u", stateDir, state.FixedClock(time.Unix(0, 0).UTC()))
	cfg := cli.Config{Parallel: 1, Limit: 10, ReposDir: reposDir}
	var stdout bytes.Buffer
	deps := Deps{
		Fetcher:      &fakeFetcher{},
		ContribFetch: func(ctx context.Context, _, _ string) ([]string, error) { return nil, nil },
		Runner:       &fakeRunner{},
		User:         "u",
		Stdin:        strings.NewReader(""),
		Stdout:       &stdout,
		Stderr:       &bytes.Buffer{},
	}
	if _, err := Run(context.Background(), cfg, store, deps); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(stdout.String(), "Nothing selected") {
		t.Errorf("missing message: %q", stdout.String())
	}
}
