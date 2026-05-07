package commit

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestBuildCommitMessage(t *testing.T) {
	tests := []struct {
		opts Options
		want string
	}{
		{Options{HadReadmeBefore: false}, "docs: add README"},
		{Options{HadReadmeBefore: true}, "docs: update README"},
		{Options{HadReadmeBefore: false, SkipCI: true}, "docs: add README [skip ci]"},
		{Options{HadReadmeBefore: true, CommitMessageOverride: "feat: x"}, "feat: x"},
		{Options{CommitMessageOverride: "x", SkipCI: true}, "x [skip ci]"},
	}
	for _, tc := range tests {
		got := BuildCommitMessage(tc.opts)
		if got != tc.want {
			t.Errorf("got %q want %q", got, tc.want)
		}
	}
}

func TestBranchName(t *testing.T) {
	got := BranchName(time.Unix(123, 0))
	if got != "docs/readme-pipeline-123" {
		t.Errorf("got %q", got)
	}
}

func TestCommitAndPushRejectsMultilineMsg(t *testing.T) {
	r := CommitAndPush(context.Background(), "/", Options{Mode: ModeDirect, CommitMessageOverride: "a\nb"})
	if r.Status != "failed" || !strings.Contains(r.Error, "single line") {
		t.Errorf("got %+v", r)
	}
}

func TestCommitAndPushSkip(t *testing.T) {
	r := CommitAndPush(context.Background(), "/", Options{Mode: ModeSkip})
	if r.Status != "skipped" {
		t.Errorf("got %+v", r)
	}
}

func gitInit(t *testing.T, dir string) {
	t.Helper()
	for _, args := range [][]string{
		{"git", "init", "-q", "-b", "main"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = dir
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("%v %s", err, out)
		}
	}
}

func TestCommitAndPushCommitOnly(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("hi"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	r := CommitAndPush(context.Background(), dir, Options{Mode: ModeCommitOnly})
	if r.Status != "commit_only" {
		t.Errorf("got %+v", r)
	}
}

func TestCommitAndPushDirectDryRun(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	r := CommitAndPush(context.Background(), dir, Options{Mode: ModeDirect, DryRun: true})
	if r.Status != "pushed" || r.Mode != "direct" {
		t.Errorf("got %+v", r)
	}
}

func TestCommitAndPushPRDryRun(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	r := CommitAndPush(context.Background(), dir, Options{Mode: ModePR, DryRun: true, HadReadmeBefore: true})
	if r.Status != "pr_opened" {
		t.Errorf("got %+v", r)
	}
}

func TestWarnGPGSigning(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	for _, args := range [][]string{
		{"git", "config", "commit.gpgsign", "true"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = dir
		_, _ = c.CombinedOutput()
	}
	var buf bytes.Buffer
	WarnGPGSigning(context.Background(), dir, &buf)
	if !strings.Contains(buf.String(), "GPG signing") {
		t.Errorf("got %q", buf.String())
	}
}

func TestEnsureReposDir(t *testing.T) {
	d := filepath.Join(t.TempDir(), "x")
	if err := EnsureReposDir(d); err != nil {
		t.Fatal(err)
	}
	if info, err := os.Stat(d); err != nil || !info.IsDir() {
		t.Error("not dir")
	}
}

func setupRepoWithRemote(t *testing.T) (workdir, bare string) {
	t.Helper()
	bare = filepath.Join(t.TempDir(), "origin.git")
	c := exec.Command("git", "init", "--bare", "-q", "-b", "main", bare)
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("init bare: %v %s", err, out)
	}
	workdir = filepath.Join(t.TempDir(), "wd")
	if err := os.MkdirAll(workdir, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"git", "init", "-q", "-b", "main"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", "-q"},
		{"git", "remote", "add", "origin", bare},
		{"git", "push", "-u", "origin", "main", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = workdir
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("%v: %v %s", args, err, out)
		}
	}
	return workdir, bare
}

func TestCommitAndPushDirectReal(t *testing.T) {
	wd, _ := setupRepoWithRemote(t)
	if err := os.WriteFile(filepath.Join(wd, "README.md"), []byte("hi"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	r := CommitAndPush(context.Background(), wd, Options{Mode: ModeDirect})
	if r.Status != "pushed" {
		t.Errorf("got %+v", r)
	}
}

func TestCommitAndPushPRReal(t *testing.T) {
	wd, _ := setupRepoWithRemote(t)
	if err := os.WriteFile(filepath.Join(wd, "README.md"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	// gh pr create will fail (no real github); push succeeds but PR creation failure surfaces as Status="failed".
	r := CommitAndPush(context.Background(), wd, Options{Mode: ModePR})
	if r.Status != "failed" || r.Mode != "pr" {
		t.Errorf("got %+v", r)
	}
	if !strings.Contains(r.Error, "gh pr create") {
		t.Errorf("expected error from gh pr create step, got %q", r.Error)
	}
}

func TestCommitAndPushDirectFailsWithoutReadme(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	// No README.md → `git add README.md` fails.
	r := CommitAndPush(context.Background(), dir, Options{Mode: ModeDirect})
	if r.Status != "failed" {
		t.Errorf("got %+v", r)
	}
}

func TestClone(t *testing.T) {
	bare := filepath.Join(t.TempDir(), "src.git")
	c := exec.Command("git", "init", "--bare", "-q", bare)
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	dst := filepath.Join(t.TempDir(), "dst")
	if err := Clone(context.Background(), bare, dst); err != nil {
		t.Errorf("clone: %v", err)
	}
}

func TestCloneOrFetchClones(t *testing.T) {
	bare := filepath.Join(t.TempDir(), "src.git")
	c := exec.Command("git", "init", "--bare", "-q", bare)
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	dst := filepath.Join(t.TempDir(), "missing")
	if err := CloneOrFetch(context.Background(), bare, dst); err != nil {
		t.Errorf("got %v", err)
	}
}

func TestCloneOrFetchExisting(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	// Add a remote so fetch has somewhere to talk to.
	bare := filepath.Join(t.TempDir(), "bare.git")
	c := exec.Command("git", "init", "--bare", "-q", bare)
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	c2 := exec.Command("git", "remote", "add", "origin", bare)
	c2.Dir = dir
	if out, err := c2.CombinedOutput(); err != nil {
		t.Fatalf("add remote: %v %s", err, out)
	}
	// Seed bare with a ref so shallow fetch succeeds.
	c3 := exec.Command("git", "push", "-q", "origin", "main")
	c3.Dir = dir
	if out, err := c3.CombinedOutput(); err != nil {
		t.Fatalf("push to bare: %v %s", err, out)
	}
	// Should detect .git and call Fetch.
	if err := CloneOrFetch(context.Background(), bare, dir); err != nil {
		t.Fatalf("clone/fetch existing repo: %v", err)
	}
}
