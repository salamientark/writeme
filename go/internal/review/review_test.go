package review

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestSkillMDEmbedded(t *testing.T) {
	if !strings.Contains(SkillMD, "name: create-readme") {
		t.Fatalf("embedded SKILL.md missing frontmatter; got %q", SkillMD[:min(100, len(SkillMD))])
	}
}

func TestScrubEnv(t *testing.T) {
	base := []string{
		"PATH=/usr/bin",
		"AWS_SECRET_ACCESS_KEY=leak",
		"GITHUB_TOKEN=leak",
		"HOME=/home/u",
		"CLAUDE_API_KEY=keep",
		"LC_ALL=C",
		"XDG_CONFIG_HOME=/x",
		"GH_USER=u",
	}
	got := ScrubEnv(base, []string{"XDG_CACHE_HOME=/c"})
	want := map[string]bool{
		"PATH=/usr/bin":       true,
		"HOME=/home/u":        true,
		"CLAUDE_API_KEY=keep": true,
		"LC_ALL=C":            true,
		"XDG_CONFIG_HOME=/x":  true,
		"XDG_CACHE_HOME=/c":   true,
	}
	for kv := range want {
		found := false
		for _, g := range got {
			if g == kv {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("missing %q", kv)
		}
	}
	for _, kv := range got {
		if strings.HasPrefix(kv, "AWS_") || strings.HasPrefix(kv, "GITHUB_") || strings.HasPrefix(kv, "GH_") {
			t.Errorf("leaked: %q", kv)
		}
	}
}

func TestStageSkill(t *testing.T) {
	dir := t.TempDir()
	cleanup, err := StageSkill(dir)
	if err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dir, ".claude", "skills", "create-readme", "SKILL.md")
	b, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != SkillMD {
		t.Error("content mismatch")
	}
	cleanup()
	if _, err := os.Stat(dst); !errors.Is(err, os.ErrNotExist) {
		t.Error("cleanup")
	}
}

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

type fakeRunner struct {
	exitCode int
	err      error
	produce  string
	extra    bool
}

func (f *fakeRunner) Run(ctx context.Context, repoDir string, env []string) (int, string, error) {
	if f.produce != "" {
		_ = os.WriteFile(filepath.Join(repoDir, "README.md"), []byte(f.produce), 0o644)
	}
	if f.extra {
		_ = os.WriteFile(filepath.Join(repoDir, "OTHER.txt"), []byte("oops"), 0o644)
	}
	return f.exitCode, "", f.err
}

func TestGenerateDraftReady(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	got, err := GenerateDraft(context.Background(), &fakeRunner{produce: "# Hello"}, dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != StatusReady || got.NewContent != "# Hello" {
		t.Errorf("got %+v", got)
	}
}

func TestGenerateDraftNonzero(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	got, _ := GenerateDraft(context.Background(), &fakeRunner{exitCode: 1}, dir, nil)
	if got.Status != StatusNonzero {
		t.Errorf("got %+v", got)
	}
}

func TestGenerateDraftTimeout(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	got, _ := GenerateDraft(context.Background(), &fakeRunner{err: context.DeadlineExceeded}, dir, nil)
	if got.Status != StatusTimeout {
		t.Errorf("got %+v", got)
	}
}

func TestGenerateDraftBlastRadius(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	got, _ := GenerateDraft(context.Background(), &fakeRunner{produce: "# OK", extra: true}, dir, nil)
	if got.Status != StatusBlastRadius {
		t.Errorf("got %+v", got)
	}
}

func TestShellRunnerSuccess(t *testing.T) {
	dir := t.TempDir()
	claude := filepath.Join(dir, "claude")
	if err := os.WriteFile(claude, []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+":/usr/bin:/bin")
	code, _, err := (ShellRunner{}).Run(context.Background(), dir, []string{"PATH=" + dir + ":/usr/bin:/bin"})
	if err != nil {
		t.Fatalf("got %v", err)
	}
	if code != 0 {
		t.Errorf("code=%d", code)
	}
}

func TestShellRunnerNonzero(t *testing.T) {
	dir := t.TempDir()
	claude := filepath.Join(dir, "claude")
	_ = os.WriteFile(claude, []byte("#!/bin/sh\nexit 7\n"), 0o755)
	t.Setenv("PATH", dir+":/usr/bin:/bin")
	code, _, err := (ShellRunner{}).Run(context.Background(), dir, []string{"PATH=" + dir + ":/usr/bin:/bin"})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if code != 7 {
		t.Errorf("code=%d", code)
	}
}

func TestShellRunnerMissingBinary(t *testing.T) {
	t.Setenv("PATH", "")
	dir := t.TempDir()
	if _, _, err := (ShellRunner{}).Run(context.Background(), dir, nil); err == nil {
		t.Error("want err")
	}
}

func TestGenerateDraftRunError(t *testing.T) {
	dir := t.TempDir()
	gitInit(t, dir)
	got, _ := GenerateDraft(context.Background(), &fakeRunner{err: errors.New("explode")}, dir, nil)
	if got.Status != StatusFailed {
		t.Errorf("got %+v", got)
	}
}
