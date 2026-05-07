package diff

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func gitInit(t *testing.T, dir string) {
	t.Helper()
	for _, args := range [][]string{
		{"git", "init", "-q"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = dir
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("%v %s", err, out)
		}
	}
}

func TestPlain(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("# old\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"git", "add", "README.md"},
		{"git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "r", "-q"},
	} {
		c := exec.Command(args[0], args[1:]...)
		c.Dir = dir
		_, _ = c.CombinedOutput()
	}
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("# new\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	out, err := Plain(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "# new") {
		t.Errorf("got %q", out)
	}
}

func TestPlainNoRepo(t *testing.T) {
	if _, err := Plain(context.Background(), t.TempDir()); err == nil {
		t.Error("want err")
	}
}
