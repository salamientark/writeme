package pipeline

import (
	"fmt"
	"io"

	"github.com/salamientark/writeme/internal/state"
)

// summaryLabels mirrors the Python label_map order from gh_readme_pipeline._print_summary.
var summaryLabels = []struct {
	Status string
	Label  string
}{
	{state.StatusPROpened, "Pushed (PR)"},
	{state.StatusPushed, "Pushed (direct)"},
	{state.StatusCommitOnly, "Commit only"},
	{state.StatusSkipped, "Skipped"},
	{state.StatusFailed, "Failed"},
}

// PrintSummary writes the end-of-run summary block to w in a format that is
// byte-for-byte identical to the Python pipeline's _print_summary (G8).
func PrintSummary(w io.Writer, sum state.Summary) {
	fmt.Fprintln(w, "\n--- Summary ---")
	for _, e := range summaryLabels {
		fmt.Fprintf(w, "  %-20s %d\n", e.Label, sum.Counts[e.Status])
	}
	if len(sum.PRURLs) > 0 {
		fmt.Fprintln(w, "\nPR URLs:")
		for _, u := range sum.PRURLs {
			fmt.Fprintf(w, "  %s\n", u)
		}
	}
	if len(sum.FailedRepos) > 0 {
		fmt.Fprintln(w, "\nFailed repos:")
		for _, r := range sum.FailedRepos {
			fmt.Fprintf(w, "  %s\n", r)
		}
	}
}
