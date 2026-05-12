package state

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func osOpenAppend(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
}

func newStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	ts, _ := time.Parse(time.RFC3339, "2026-05-07T10:50:00Z")
	s, err := New("testuser", dir, FixedClock(ts))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestValidateGHUser(t *testing.T) {
	good := []string{"a", "octocat", "Foo-Bar9", strings.Repeat("a", 39)}
	bad := []string{"", "-leading", "trailing-", "double--hyphen", "with space", strings.Repeat("a", 40)}
	for _, n := range good {
		if err := ValidateGHUser(n); err != nil {
			t.Errorf("good %q: %v", n, err)
		}
	}
	for _, n := range bad {
		if err := ValidateGHUser(n); err == nil {
			t.Errorf("bad %q: want err", n)
		}
	}
}

func TestRecordAndSummary(t *testing.T) {
	s := newStore(t)
	if s.HasPriorState() {
		t.Fatal("unexpected prior")
	}
	if err := s.Record("a", StatusPushed, RecordOpts{Mode: "direct"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Record("b", StatusPROpened, RecordOpts{Mode: "pr", PRURL: "https://x/1"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Record("c", StatusFailed, RecordOpts{Error: "boom"}); err != nil {
		t.Fatal(err)
	}
	if !s.HasPriorState() {
		t.Fatal("want prior")
	}
	sum, err := s.Summary()
	if err != nil {
		t.Fatal(err)
	}
	if sum.Counts[StatusPushed] != 1 || sum.Counts[StatusPROpened] != 1 || sum.Counts[StatusFailed] != 1 {
		t.Errorf("counts: %+v", sum.Counts)
	}
	if len(sum.PRURLs) != 1 || sum.PRURLs[0] != "https://x/1" {
		t.Errorf("PR urls: %+v", sum.PRURLs)
	}
	if len(sum.FailedRepos) != 1 || sum.FailedRepos[0] != "c" {
		t.Errorf("failed: %+v", sum.FailedRepos)
	}
}

func TestLoadProcessedLastRecordWins(t *testing.T) {
	s := newStore(t)
	_ = s.Record("a", StatusFailed, RecordOpts{Error: "x"})
	_ = s.Record("a", StatusPushed, RecordOpts{Mode: "direct"})
	_ = s.Record("b", StatusPushed, RecordOpts{})
	_ = s.Record("b", StatusFailed, RecordOpts{Error: "y"})
	got, err := s.LoadProcessed()
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := got["a"]; !ok {
		t.Error("a should be processed (last=pushed)")
	}
	if _, ok := got["b"]; ok {
		t.Error("b last=failed → not processed")
	}
}

func TestSkipMalformedLines(t *testing.T) {
	s := newStore(t)
	_ = s.Record("a", StatusPushed, RecordOpts{})
	if err := appendRaw(s.File(), "not-json\n"); err != nil {
		t.Fatal(err)
	}
	_ = s.Record("b", StatusPushed, RecordOpts{})
	sum, _ := s.Summary()
	if sum.Counts[StatusPushed] != 2 {
		t.Errorf("got %d", sum.Counts[StatusPushed])
	}
}

func appendRaw(path, s string) error {
	f, err := osOpenAppend(path)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(s)
	return err
}

func TestRecordRace(t *testing.T) {
	s := newStore(t)
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_ = s.Record("r", StatusPushed, RecordOpts{})
		}(i)
	}
	wg.Wait()
	sum, _ := s.Summary()
	if sum.Counts[StatusPushed] != 20 {
		t.Errorf("got %d want 20", sum.Counts[StatusPushed])
	}
}

func TestPromptResumeLoopsOnInvalid(t *testing.T) {
	in := strings.NewReader("zzz\n\n  R \n")
	var out bytes.Buffer
	got, err := PromptResume(in, &out, 5)
	if err != nil {
		t.Fatal(err)
	}
	if got != ResumeKeep {
		t.Errorf("got %q", got)
	}
	if !strings.Contains(out.String(), "Found 5 repos") {
		t.Error("missing prompt")
	}
}

func TestNewRejectsBadUser(t *testing.T) {
	if _, err := New("bad user", t.TempDir(), nil); err == nil {
		t.Error("want err")
	}
	if _, err := New("good", t.TempDir(), nil); err != nil {
		t.Errorf("nil clock should default: %v", err)
	}
}

func TestRealClockMonotonic(t *testing.T) {
	c := RealClock()
	now := c.Now()
	if now.IsZero() {
		t.Error("zero")
	}
}

func TestPromptResumeAllChoices(t *testing.T) {
	cases := map[string]ResumeChoice{"a\n": ResumeAll, "s\n": ResumeFresh, "q\n": ResumeQuit}
	for in, want := range cases {
		got, err := PromptResume(strings.NewReader(in), &bytes.Buffer{}, 0)
		if err != nil || got != want {
			t.Errorf("in=%q got=%q err=%v", in, got, err)
		}
	}
}

func TestPromptResumeEOF(t *testing.T) {
	if _, err := PromptResume(strings.NewReader(""), &bytes.Buffer{}, 0); err == nil {
		t.Error("want err on EOF")
	}
}

func TestFilePath(t *testing.T) {
	s := newStore(t)
	if filepath.Base(s.File()) != "state-testuser.jsonl" {
		t.Error(s.File())
	}
}
