// Package filters: range parser + repo predicates.
package filters

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Repo is the minimal subset filters operate on. Mirrors fetch.Repo fields.
type Repo struct {
	Name            string
	SSHURL          string
	PushedAt        string
	HadReadmeBefore bool
	DiskUsage       int
	IsFork          bool
	Contributors    []string
	HasContributors bool // true once contributor enrichment has run
}

// IsSolo reports whether contributors ≤ 1 (post-bot-strip). False if not enriched.
func IsSolo(r Repo) bool {
	if !r.HasContributors {
		return false
	}
	return len(r.Contributors) <= 1
}

// IsFork wraps the bool field.
func IsFork(r Repo) bool { return r.IsFork }

// HasReadme wraps HadReadmeBefore.
func HasReadme(r Repo) bool { return r.HadReadmeBefore }

// Apply returns repos passing every enabled toggle (AND composition).
func Apply(repos []Repo, soloOnly, excludeForks, excludeExistingReadme bool) []Repo {
	out := make([]Repo, 0, len(repos))
	for _, r := range repos {
		if soloOnly && !IsSolo(r) {
			continue
		}
		if excludeForks && r.IsFork {
			continue
		}
		if excludeExistingReadme && r.HadReadmeBefore {
			continue
		}
		out = append(out, r)
	}
	return out
}

// ParseKind labels the outcome of ParseSelection.
type ParseKind int

const (
	ParseOK ParseKind = iota
	ParseAll
	ParseQuit
	ParseError
)

// ParseResult is the structured outcome of selection input.
type ParseResult struct {
	Kind    ParseKind
	Indices []int // sorted, 0-indexed
	Message string
}

// ParseSelection parses "1,3,5-7" / "a" / "q" / "" → ParseResult.
// total is the upper-bound (1-indexed input range).
func ParseSelection(raw string, total int) ParseResult {
	s := strings.ToLower(strings.TrimSpace(raw))
	switch s {
	case "", "q":
		return ParseResult{Kind: ParseQuit}
	case "a":
		return ParseResult{Kind: ParseAll}
	}
	set := map[int]struct{}{}
	for _, tok := range strings.Split(s, ",") {
		t := strings.TrimSpace(tok)
		if t == "" {
			return ParseResult{Kind: ParseError, Message: fmt.Sprintf("empty token in %q", raw)}
		}
		if strings.Contains(t, "-") {
			parts := strings.Split(t, "-")
			if len(parts) != 2 {
				return ParseResult{Kind: ParseError, Message: fmt.Sprintf("bad range %q", t)}
			}
			lo, errLo := strconv.Atoi(strings.TrimSpace(parts[0]))
			hi, errHi := strconv.Atoi(strings.TrimSpace(parts[1]))
			if errLo != nil || errHi != nil {
				return ParseResult{Kind: ParseError, Message: fmt.Sprintf("bad range %q", t)}
			}
			if lo < 1 || hi > total || lo > hi {
				return ParseResult{Kind: ParseError, Message: fmt.Sprintf("range %q out of bounds (1..%d)", t, total)}
			}
			for i := lo; i <= hi; i++ {
				set[i-1] = struct{}{}
			}
			continue
		}
		n, err := strconv.Atoi(t)
		if err != nil {
			return ParseResult{Kind: ParseError, Message: fmt.Sprintf("bad token %q", t)}
		}
		if n < 1 || n > total {
			return ParseResult{Kind: ParseError, Message: fmt.Sprintf("index %d out of bounds (1..%d)", n, total)}
		}
		set[n-1] = struct{}{}
	}
	out := make([]int, 0, len(set))
	for i := range set {
		out = append(out, i)
	}
	sort.Ints(out)
	return ParseResult{Kind: ParseOK, Indices: out}
}
