package contributors

import (
	"context"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
)

func TestIsBotAndStrip(t *testing.T) {
	bots := []string{"dependabot[bot]", "github-actions", "dependabot", "dependabot-preview", "renovate[bot]"}
	humans := []string{"alice", "bob123", "github-helper"}
	for _, b := range bots {
		if !IsBot(b) {
			t.Errorf("expect bot: %q", b)
		}
	}
	for _, h := range humans {
		if IsBot(h) {
			t.Errorf("not bot: %q", h)
		}
	}
	got := StripBots([]string{"alice", "dependabot[bot]", "bob"})
	if len(got) != 2 || got[0] != "alice" || got[1] != "bob" {
		t.Errorf("got %v", got)
	}
}

func TestCacheRoundtrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "c.json")
	in := map[string][]string{"a@2026": {"u1"}, "b@2026": {}}
	if err := SaveCache(path, in); err != nil {
		t.Fatal(err)
	}
	got := LoadCache(path)
	if len(got) != 2 || got["a@2026"][0] != "u1" {
		t.Errorf("got %v", got)
	}
}

func TestLoadCacheCorrupt(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "c.json")
	if got := LoadCache(path); len(got) != 0 {
		t.Error("missing should be empty")
	}
	if err := os.WriteFile(path, []byte("{not-json"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := LoadCache(path); len(got) != 0 {
		t.Errorf("corrupt should be empty, got %v", got)
	}
}

func TestEnrichFetchError(t *testing.T) {
	fake := func(ctx context.Context, owner, name string) ([]string, error) {
		return nil, context.DeadlineExceeded
	}
	repos := []Repo{{Name: "x", PushedAt: "p"}}
	_, err := Enrich(context.Background(), "o", repos, filepath.Join(t.TempDir(), "c.json"), fake, 1)
	if err == nil {
		t.Fatal("want err")
	}
}

func TestShellFetchMissingBinary(t *testing.T) {
	t.Setenv("PATH", "")
	got, err := ShellFetch(context.Background(), "o", "r")
	if err == nil {
		t.Error("want err when gh binary missing")
	}
	if got != nil {
		t.Errorf("got %v, want nil", got)
	}
}

func TestShellFetchExitError(t *testing.T) {
	dir := t.TempDir()
	gh := filepath.Join(dir, "gh")
	if err := os.WriteFile(gh, []byte("#!/bin/sh\nexit 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	got, err := ShellFetch(context.Background(), "o", "r")
	if err != nil {
		t.Errorf("exit-err should swallow: %v", err)
	}
	if got != nil {
		t.Errorf("got %v", got)
	}
}

func TestShellFetchSuccess(t *testing.T) {
	dir := t.TempDir()
	gh := filepath.Join(dir, "gh")
	body := "#!/bin/sh\nprintf '[{\"login\":\"alice\"},{\"login\":\"dependabot[bot]\"}]'\n"
	if err := os.WriteFile(gh, []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	got, err := ShellFetch(context.Background(), "o", "r")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0] != "alice" {
		t.Errorf("got %v", got)
	}
}

func TestSaveCacheBadDir(t *testing.T) {
	// Writing to a path under a file (not dir) → mkdir error.
	tmp := t.TempDir()
	conflict := filepath.Join(tmp, "blocker")
	_ = os.WriteFile(conflict, []byte("x"), 0o644)
	if err := SaveCache(filepath.Join(conflict, "sub", "c.json"), nil); err == nil {
		t.Error("want err")
	}
}

func TestShellFetchBadJSON(t *testing.T) {
	dir := t.TempDir()
	gh := filepath.Join(dir, "gh")
	if err := os.WriteFile(gh, []byte("#!/bin/sh\nprintf 'not json'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	got, err := ShellFetch(context.Background(), "o", "r")
	if err != nil {
		t.Errorf("bad json should swallow: %v", err)
	}
	if got != nil {
		t.Errorf("got %v", got)
	}
}

func TestEnrichMaxWorkersZero(t *testing.T) {
	fake := func(ctx context.Context, owner, name string) ([]string, error) { return []string{"u"}, nil }
	repos := []Repo{{Name: "a", PushedAt: "p"}}
	got, err := Enrich(context.Background(), "o", repos, filepath.Join(t.TempDir(), "c.json"), fake, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 {
		t.Errorf("got %v", got)
	}
}

func TestEnrichSaveCacheError(t *testing.T) {
	fake := func(ctx context.Context, owner, name string) ([]string, error) { return []string{"u"}, nil }
	tmp := t.TempDir()
	blocker := filepath.Join(tmp, "blocker")
	_ = os.WriteFile(blocker, []byte("x"), 0o644)
	cachePath := filepath.Join(blocker, "sub", "c.json")
	repos := []Repo{{Name: "a", PushedAt: "p"}}
	_, err := Enrich(context.Background(), "o", repos, cachePath, fake, 1)
	if err == nil {
		t.Fatal("want err")
	}
}

func TestEnrichEmpty(t *testing.T) {
	fake := func(ctx context.Context, owner, name string) ([]string, error) { return nil, nil }
	got, err := Enrich(context.Background(), "o", nil, filepath.Join(t.TempDir(), "c.json"), fake, 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Error(got)
	}
}

func TestEnrich(t *testing.T) {
	var calls int32
	fake := func(ctx context.Context, owner, name string) ([]string, error) {
		atomic.AddInt32(&calls, 1)
		switch name {
		case "solo":
			return []string{"alice"}, nil
		case "team":
			return []string{"alice", "bob", "dependabot[bot]"}, nil
		}
		return nil, nil
	}
	cachePath := filepath.Join(t.TempDir(), "c.json")
	repos := []Repo{{Name: "solo", PushedAt: "p1"}, {Name: "team", PushedAt: "p2"}}
	got, err := Enrich(context.Background(), "owner", repos, cachePath, fake, 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatal(got)
	}
	if calls != 2 {
		t.Errorf("calls=%d", calls)
	}
	// 2nd run should hit cache.
	atomic.StoreInt32(&calls, 0)
	got2, err := Enrich(context.Background(), "owner", repos, cachePath, fake, 2)
	if err != nil {
		t.Fatal(err)
	}
	if calls != 0 {
		t.Errorf("expected cache hit, calls=%d", calls)
	}
	for _, r := range got2 {
		if r.Repo.Name == "team" && len(r.Contributors) != 3 {
			t.Errorf("team contribs=%v, want 3 (raw fetch, no bot strip)", r.Contributors)
		}
	}
}
