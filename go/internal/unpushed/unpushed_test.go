package unpushed

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func gitInit(t *testing.T, dir string) {
	t.Helper()
	for _, args := range [][]string{
		{"git", "init", "-q"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", "-q"},
	} {
		cmd := exec.Command(args[0], args[1:]...)
		cmd.Dir = dir
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("%v %s: %v %s", args, dir, err, out)
		}
	}
}

func TestScanMissingDir(t *testing.T) {
	got, err := Scan(context.Background(), filepath.Join(t.TempDir(), "no"))
	if err != nil {
		t.Fatal(err)
	}
	if got != nil {
		t.Errorf("got %v", got)
	}
}

func TestScanCleanRepo(t *testing.T) {
	root := t.TempDir()
	repo := filepath.Join(root, "r1")
	_ = os.MkdirAll(repo, 0o755)
	gitInit(t, repo)
	got, err := Scan(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Errorf("clean: %v", got)
	}
}

func TestScanDetectsDirty(t *testing.T) {
	root := t.TempDir()
	repo := filepath.Join(root, "r1")
	_ = os.MkdirAll(repo, 0o755)
	gitInit(t, repo)
	if err := os.WriteFile(filepath.Join(repo, "x.txt"), []byte("y"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := Scan(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || !got[0].Dirty {
		t.Errorf("got %+v", got)
	}
}

func TestScanWithUpstream(t *testing.T) {
	root := t.TempDir()
	bare := filepath.Join(root, "origin.git")
	cmd := exec.Command("git", "init", "--bare", "-q", bare)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	repo := filepath.Join(root, "r1")
	_ = os.MkdirAll(repo, 0o755)
	gitInit(t, repo)
	for _, args := range [][]string{
		{"git", "remote", "add", "origin", bare},
		{"git", "push", "-u", "origin", "HEAD:main", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = repo
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("%v %s", err, out)
		}
	}
	// Add a commit but don't push.
	_ = os.WriteFile(filepath.Join(repo, "x.txt"), []byte("y"), 0o644)
	for _, args := range [][]string{
		{"git", "add", "x.txt"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "x", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = repo
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("%v %s", err, out)
		}
	}
	got, err := Scan(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].UnpushedCommits != 1 {
		t.Errorf("got %+v", got)
	}
}

func TestScanSkipsNonGit(t *testing.T) {
	root := t.TempDir()
	_ = os.MkdirAll(filepath.Join(root, "plain"), 0o755)
	got, err := Scan(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Errorf("got %v", got)
	}
}
