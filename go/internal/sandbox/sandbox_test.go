package sandbox

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

func TestJobSandboxCreatesDirs(t *testing.T) {
	base := t.TempDir()
	job, err := JobSandbox(base, "myrepo")
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(base, "claude-jobs", "myrepo")
	if job.Root != want {
		t.Errorf("Root=%q want %q", job.Root, want)
	}
	for _, sub := range SubDirs {
		info, err := os.Stat(filepath.Join(want, sub))
		if err != nil {
			t.Fatal(err)
		}
		if !info.IsDir() {
			t.Errorf("%s not dir", sub)
		}
	}
}

func TestJobSandboxRejectsBadName(t *testing.T) {
	if _, err := JobSandbox(t.TempDir(), "../escape"); err == nil {
		t.Fatal("want validation error")
	}
}

func TestEnvFor(t *testing.T) {
	job, err := JobSandbox(t.TempDir(), "r")
	if err != nil {
		t.Fatal(err)
	}
	env := EnvFor(job)
	sort.Strings(env)
	wanted := []string{"XDG_CACHE_HOME=", "XDG_CONFIG_HOME=", "XDG_DATA_HOME=", "XDG_STATE_HOME="}
	for _, prefix := range wanted {
		found := false
		for _, e := range env {
			if strings.HasPrefix(e, prefix) {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("missing %s", prefix)
		}
	}
}

func TestCleanup(t *testing.T) {
	base := t.TempDir()
	job, _ := JobSandbox(base, "r")
	if err := job.Cleanup(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(job.Root); !os.IsNotExist(err) {
		t.Error("root should be removed")
	}
}
