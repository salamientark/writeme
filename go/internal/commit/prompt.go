package commit

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"strings"
)

// PromptMode asks the user for ship mode honoring ctx cancellation.
// Returns ModeSkip on ctx cancellation or EOF.
func PromptMode(ctx context.Context, r *bufio.Reader, w io.Writer) Mode {
	type result struct {
		line string
		err  error
	}
	for {
		fmt.Fprint(w, "Mode? [p]r / [m]ain (direct) / [c]ommit-only / [n]o: ")
		ch := make(chan result, 1)
		go func() {
			s, err := r.ReadString('\n')
			ch <- result{s, err}
		}()
		select {
		case <-ctx.Done():
			return ModeSkip
		case res := <-ch:
			if res.err != nil && res.line == "" {
				return ModeSkip
			}
			switch strings.ToLower(strings.TrimSpace(res.line)) {
			case "p":
				return ModePR
			case "m":
				return ModeDirect
			case "c":
				return ModeCommitOnly
			case "n":
				return ModeSkip
			}
		}
	}
}
