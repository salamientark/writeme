package safety

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestValidateRepoName(t *testing.T) {
	good := []string{"foo", "bar.baz", "foo-bar_1"}
	bad := []string{"", ".", "..", "foo/bar", "foo bar", "../etc", "$(rm)"}
	for _, n := range good {
		if err := ValidateRepoName(n); err != nil {
			t.Errorf("good %q: %v", n, err)
		}
	}
	for _, n := range bad {
		if err := ValidateRepoName(n); err == nil {
			t.Errorf("bad %q: want err", n)
		}
	}
}

func TestValidateSSHURL(t *testing.T) {
	good := []string{
		"git@github.com:o/r",
		"git@github.com:o/r.git",
		"https://github.com/o/r",
		"https://github.com/o/r.git",
	}
	bad := []string{
		"",
		"ssh://x@github.com/o/r",
		"https://gitlab.com/o/r",
		"git@github.com:o/r ; rm -rf /",
		"git@github.com:o/r/extra",
	}
	for _, u := range good {
		if err := ValidateSSHURL(u); err != nil {
			t.Errorf("good %q: %v", u, err)
		}
	}
	for _, u := range bad {
		if err := ValidateSSHURL(u); err == nil {
			t.Errorf("bad %q: want err", u)
		}
	}
}

func TestAcquireLockExcludes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "lock")
	rel1, err := AcquireLock(path)
	if err != nil {
		t.Fatal(err)
	}
	defer rel1()
	if _, err := AcquireLock(path); !errors.Is(err, ErrLocked) {
		t.Errorf("want ErrLocked, got %v", err)
	}
	if err := rel1(); err != nil {
		t.Fatal(err)
	}
	rel2, err := AcquireLock(path)
	if err != nil {
		t.Fatalf("re-acquire: %v", err)
	}
	rel2()
}

func gitInit(t *testing.T, dir string) {
	t.Helper()
	for _, args := range [][]string{
		{"git", "init", "-q"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", "-q"},
	} {
		cmd := exec.Command(args[0], args[1:]...)
		cmd.Dir = dir
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("%v: %s", err, out)
		}
	}
}

func TestEnsureCleanRemovesUntracked(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "junk.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".git", "MERGE_HEAD"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := EnsureClean(context.Background(), dir); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "junk.txt")); !errors.Is(err, os.ErrNotExist) {
		t.Error("junk should be gone")
	}
	if _, err := os.Stat(filepath.Join(dir, ".git", "MERGE_HEAD")); !errors.Is(err, os.ErrNotExist) {
		t.Error("MERGE_HEAD should be gone")
	}
}

func TestBlastRadius(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	// Only README → empty result.
	_ = os.WriteFile(filepath.Join(dir, "README.md"), []byte("hi"), 0o644)
	paths, err := BlastRadius(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 0 {
		t.Errorf("README-only should be clean, got %v", paths)
	}
	_ = os.WriteFile(filepath.Join(dir, "other.txt"), []byte("oops"), 0o644)
	paths, err = BlastRadius(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 1 || paths[0] != "other.txt" {
		t.Errorf("got %v", paths)
	}
}
