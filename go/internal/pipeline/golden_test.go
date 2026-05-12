package pipeline

import (
	"bytes"
	"os"
	"testing"
	"time"

	"github.com/salamientark/writeme/internal/state"
)

// TestGoldenSummaryByteEqual replays the Phase 0 deterministic record set and
// asserts PrintSummary produces output byte-equal to the Python golden (G8).
func TestGoldenSummaryByteEqual(t *testing.T) {
	frozen, _ := time.Parse(time.RFC3339, "2026-01-15T12:00:00Z")
	dir := t.TempDir()
	s, err := state.New("testuser", dir, state.FixedClock(frozen))
	if err != nil {
		t.Fatal(err)
	}
	mustRecord := func(repo, status string, opts state.RecordOpts) {
		t.Helper()
		if err := s.Record(repo, status, opts); err != nil {
			t.Fatal(err)
		}
	}
	mustRecord("alpha-repo", state.StatusPROpened, state.RecordOpts{Mode: "pr", PRURL: "https://github.com/testuser/alpha-repo/pull/1"})
	mustRecord("beta-repo", state.StatusPushed, state.RecordOpts{Mode: "direct"})
	mustRecord("gamma-repo", state.StatusCommitOnly, state.RecordOpts{Mode: "commit_only"})
	mustRecord("delta-repo", state.StatusSkipped, state.RecordOpts{})
	mustRecord("epsilon-repo", state.StatusFailed, state.RecordOpts{Error: "claude timeout"})

	sum, err := s.Summary()
	if err != nil {
		t.Fatal(err)
	}

	var buf bytes.Buffer
	PrintSummary(&buf, sum)

	want, err := os.ReadFile("testdata/golden/summary.txt")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(buf.Bytes(), want) {
		t.Errorf("summary not byte-equal to Python golden\n--- got ---\n%q\n--- want ---\n%q", buf.String(), string(want))
	}
}
