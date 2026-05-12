package state

import (
	"bytes"
	"os"
	"testing"
	"time"
)

// TestGoldenStateJSONLByteEqual replays the deterministic Phase 0 sequence
// from testdata/capture_goldens.py and asserts byte-for-byte equality with
// the Python-produced golden. Decisions ref: D6, G8.
func TestGoldenStateJSONLByteEqual(t *testing.T) {
	frozen, _ := time.Parse(time.RFC3339, "2026-01-15T12:00:00Z")
	dir := t.TempDir()
	s, err := New("testuser", dir, FixedClock(frozen))
	if err != nil {
		t.Fatal(err)
	}
	mustRecord := func(repo, status string, opts RecordOpts) {
		t.Helper()
		if err := s.Record(repo, status, opts); err != nil {
			t.Fatal(err)
		}
	}
	mustRecord("alpha-repo", StatusPROpened, RecordOpts{Mode: "pr", PRURL: "https://github.com/testuser/alpha-repo/pull/1"})
	mustRecord("beta-repo", StatusPushed, RecordOpts{Mode: "direct"})
	mustRecord("gamma-repo", StatusCommitOnly, RecordOpts{Mode: "commit_only"})
	mustRecord("delta-repo", StatusSkipped, RecordOpts{})
	mustRecord("epsilon-repo", StatusFailed, RecordOpts{Error: "claude timeout"})

	got, err := os.ReadFile(s.File())
	if err != nil {
		t.Fatal(err)
	}
	want, err := os.ReadFile("testdata/golden/state-testuser.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) {
		t.Errorf("state JSONL not byte-equal to Python golden\n--- got ---\n%s\n--- want ---\n%s", got, want)
	}
}
