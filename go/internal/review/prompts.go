package review

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"strings"
)

// readLineCtx reads one '\n'-terminated line from r honoring ctx cancellation.
// On cancel, returns ctx.Err(); the underlying read goroutine may leak until
// the next byte arrives — acceptable because process is exiting.
func readLineCtx(ctx context.Context, r *bufio.Reader) (string, error) {
	type result struct {
		line string
		err  error
	}
	ch := make(chan result, 1)
	go func() {
		s, err := r.ReadString('\n')
		ch <- result{s, err}
	}()
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case res := <-ch:
		return res.line, res.err
	}
}

// StdinPrompter is the production Prompter reading from a bufio.Reader.
type StdinPrompter struct {
	in  *bufio.Reader
	out io.Writer
}

// NewStdinPrompter constructs a Prompter for interactive use.
func NewStdinPrompter(in *bufio.Reader, out io.Writer) *StdinPrompter {
	return &StdinPrompter{in: in, out: out}
}

func (p *StdinPrompter) ask(ctx context.Context, prompt string) (string, error) {
	fmt.Fprint(p.out, prompt)
	line, err := readLineCtx(ctx, p.in)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(line), nil
}

// RiskyFiles → [c]ontinue / [s]kip.
func (p *StdinPrompter) RiskyFiles(ctx context.Context, risky []string) (string, error) {
	fmt.Fprintf(p.out, "\nWARNING: found %d risky file(s):\n", len(risky))
	for i, f := range risky {
		if i >= 10 {
			fmt.Fprintf(p.out, "  ... and %d more\n", len(risky)-10)
			break
		}
		fmt.Fprintf(p.out, "  %s\n", f)
	}
	for {
		raw, err := p.ask(ctx, "[c]ontinue / [s]kip > ")
		if err != nil {
			return "", err
		}
		s := strings.ToLower(raw)
		if s == "c" || s == "s" {
			return s, nil
		}
	}
}

// Timeout → [r]etry / [s]kip / [q]uit.
func (p *StdinPrompter) Timeout(ctx context.Context) (string, error) {
	for {
		raw, err := p.ask(ctx, "\nClaude timed out. [r]etry / [s]kip / [q]uit > ")
		if err != nil {
			return "", err
		}
		s := strings.ToLower(raw)
		if s == "r" || s == "s" || s == "q" {
			return s, nil
		}
	}
}

// Nonzero → [r]edo / [d]iscard.
func (p *StdinPrompter) Nonzero(ctx context.Context) (string, error) {
	for {
		raw, err := p.ask(ctx, "\nClaude exited non-zero. [r]edo / [d]iscard > ")
		if err != nil {
			return "", err
		}
		s := strings.ToLower(raw)
		if s == "r" || s == "d" {
			return s, nil
		}
	}
}

// SecretOverride requires literal "yes-i-checked" to override.
func (p *StdinPrompter) SecretOverride(ctx context.Context, matches []string) (bool, error) {
	fmt.Fprintln(p.out, "\n"+strings.Repeat("=", 60))
	fmt.Fprintln(p.out, "WARNING: POSSIBLE SECRETS DETECTED IN GENERATED README:")
	for _, m := range matches {
		fmt.Fprintf(p.out, "  %q\n", m)
	}
	fmt.Fprintln(p.out, strings.Repeat("=", 60))
	raw, err := p.ask(ctx, "Type 'yes-i-checked' to accept, anything else discards > ")
	if err != nil {
		return false, err
	}
	return raw == "yes-i-checked", nil
}

// Accept → "a"|"r"|"d"|"q". When hadReadme is true, accept requires literal
// "yes" (raw "a" re-prompts).
func (p *StdinPrompter) Accept(ctx context.Context, hadReadme bool, old, newC string) (string, error) {
	hint := "[a]ccept"
	if hadReadme {
		hint = "type 'yes'"
	}
	prompt := fmt.Sprintf("\n%s / [r]edo / [d]iscard / [q]uit > ", hint)
	for {
		raw, err := p.ask(ctx, prompt)
		if err != nil {
			return "", err
		}
		switch raw {
		case "r":
			return "r", nil
		case "d":
			return "d", nil
		case "q":
			return "q", nil
		}
		if hadReadme {
			if raw == "yes" {
				return "a", nil
			}
			fmt.Fprintln(p.out, "  (type 'yes' to confirm accept, or r/d/q)")
			continue
		}
		if raw == "a" {
			return "a", nil
		}
	}
}
