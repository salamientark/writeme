// Package selection: render-free plain-mode repo selection prompt.
package selection

import (
	"bufio"
	"fmt"
	"io"

	"github.com/salamientark/writeme/internal/fetch"
	"github.com/salamientark/writeme/internal/filters"
)

// RenderPlain writes a numbered list of repos.
func RenderPlain(w io.Writer, repos []fetch.Repo) {
	for i, r := range repos {
		fmt.Fprintf(w, "%4d  %s\n", i+1, r.Name)
	}
}

// Prompt reads a selection line from stdin until input parses successfully
// or returns Quit. Returns 0-indexed positions into repos (or all/empty).
func Prompt(stdin io.Reader, stdout io.Writer, total int) ([]int, error) {
	r, ok := stdin.(*bufio.Reader)
	if !ok {
		r = bufio.NewReader(stdin)
	}
	for {
		fmt.Fprintf(stdout, "Select repos (e.g. 1,3-5,8 or 'all'): ")
		line, err := r.ReadString('\n')
		if err != nil && line == "" {
			return nil, fmt.Errorf("read stdin: %w", err)
		}
		res := filters.ParseSelection(line, total)
		switch res.Kind {
		case filters.ParseQuit:
			return nil, nil
		case filters.ParseAll:
			out := make([]int, total)
			for i := range out {
				out[i] = i
			}
			return out, nil
		case filters.ParseOK:
			return res.Indices, nil
		case filters.ParseError:
			fmt.Fprintf(stdout, "  %s\n", res.Message)
		}
	}
}
