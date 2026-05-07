package fetch

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func makePage(nodes []map[string]any, hasNext bool, cursor string, remaining int) []byte {
	page := map[string]any{
		"data": map[string]any{
			"user": map[string]any{
				"repositories": map[string]any{
					"nodes":    nodes,
					"pageInfo": map[string]any{"hasNextPage": hasNext, "endCursor": cursor},
				},
			},
			"rateLimit": map[string]any{"remaining": remaining, "resetAt": ""},
		},
	}
	b, _ := json.Marshal(page)
	return b
}

func newNode(name string, hasReadme, fork bool, pushed string) map[string]any {
	n := map[string]any{
		"name":      name,
		"sshUrl":    "git@github.com:o/" + name,
		"pushedAt":  pushed,
		"diskUsage": 100,
		"isFork":    fork,
	}
	if hasReadme {
		n["readmeMd"] = map[string]any{"text": "x"}
	}
	return n
}

func TestListReposSinglePage(t *testing.T) {
	nodes := []map[string]any{
		newNode("a", true, false, "2026-05-01T00:00:00Z"),
		newNode("b", false, true, "2026-05-02T00:00:00Z"),
	}
	var stderr bytes.Buffer
	f := &GHFetcher{
		Run: func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
			return makePage(nodes, false, "", 1000), nil
		},
		Stderr: &stderr,
	}
	got, err := f.ListRepos(context.Background(), "octocat", 50)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("want 2 got %d", len(got))
	}
	// sorted by pushedAt desc
	if got[0].Name != "b" {
		t.Errorf("sort: %v", got)
	}
	if !got[1].HadReadmeBefore {
		t.Error("a has readme")
	}
}

func TestListReposPagination(t *testing.T) {
	pages := [][]byte{
		makePage([]map[string]any{newNode("a", false, false, "2026-01-01T00:00:00Z")}, true, "C1", 100),
		makePage([]map[string]any{newNode("b", false, false, "2026-02-01T00:00:00Z")}, false, "", 100),
	}
	var i int
	f := &GHFetcher{
		Run: func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
			out := pages[i]
			i++
			return out, nil
		},
		Stderr: &bytes.Buffer{},
	}
	got, err := f.ListRepos(context.Background(), "u", 50)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Errorf("got %d", len(got))
	}
	if i != 2 {
		t.Errorf("pages called=%d", i)
	}
}

func TestListReposCapWarn(t *testing.T) {
	var stderr bytes.Buffer
	f := &GHFetcher{
		Run: func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
			return makePage(nil, false, "", 1000), nil
		},
		Stderr: &stderr,
	}
	_, err := f.ListRepos(context.Background(), "u", 9999)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(stderr.String(), "capped at 1000") {
		t.Errorf("want warning, got %q", stderr.String())
	}
}

func TestListReposRateLimitSleep(t *testing.T) {
	// remaining=5 triggers sleep; resetAt empty → 0 wait, no real delay.
	var stderr bytes.Buffer
	f := &GHFetcher{
		Run: func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
			return makePage(nil, false, "", 5), nil
		},
		Stderr: &stderr,
	}
	if _, err := f.ListRepos(context.Background(), "u", 10); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(stderr.String(), "Rate limit low") {
		t.Errorf("want rate-limit warning, got %q", stderr.String())
	}
}

func TestTimeUntil(t *testing.T) {
	if d := timeUntil(""); d != 0 {
		t.Errorf("empty: %v", d)
	}
	if d := timeUntil("not-a-time"); d != 0 {
		t.Errorf("bad: %v", d)
	}
	if d := timeUntil("2000-01-01T00:00:00Z"); d != 0 {
		t.Errorf("past: %v", d)
	}
}

func TestNewGHFetcher(t *testing.T) {
	f := NewGHFetcher(&bytes.Buffer{})
	if f == nil || f.Run == nil {
		t.Fatal("constructor")
	}
}

func TestShellRunBadBinary(t *testing.T) {
	// Empty PATH → gh not found → exec error propagated.
	t.Setenv("PATH", "")
	if _, err := shellRun(context.Background(), "u", 1, ""); err == nil {
		t.Error("want exec err")
	}
}

func TestListReposBadJSON(t *testing.T) {
	f := &GHFetcher{
		Run: func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
			return []byte("not-json"), nil
		},
		Stderr: &bytes.Buffer{},
	}
	if _, err := f.ListRepos(context.Background(), "u", 10); err == nil {
		t.Fatal("want decode err")
	}
}

func TestListReposRejectsBadName(t *testing.T) {
	bad := newNode("../escape", false, false, "")
	f := &GHFetcher{
		Run: func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
			return makePage([]map[string]any{bad}, false, "", 1000), nil
		},
		Stderr: &bytes.Buffer{},
	}
	if _, err := f.ListRepos(context.Background(), "u", 10); err == nil {
		t.Fatal("want validation err")
	}
}
