package review

import (
	"context"
	"errors"
	"testing"
)

// fakePrompter records calls and replays scripted answers per prompt type.
type fakePrompter struct {
	risky         []string // returned in order: "c"|"s"
	timeout       []string // "r"|"s"|"q"
	nonzero       []string // "r"|"d"
	secret        []bool   // true ⇒ override
	accept        []string // "a"|"r"|"d"|"q"|"v"|"V"|"o" — "v"/"V"/"o" loop
	calls         []string
	acceptCtxSnap []acceptSnap
}

type acceptSnap struct {
	hadReadme bool
	old, new  string
}

func (f *fakePrompter) RiskyFiles(ctx context.Context, risky []string) (string, error) {
	f.calls = append(f.calls, "risky")
	v := f.risky[0]
	f.risky = f.risky[1:]
	return v, nil
}
func (f *fakePrompter) Timeout(ctx context.Context) (string, error) {
	f.calls = append(f.calls, "timeout")
	v := f.timeout[0]
	f.timeout = f.timeout[1:]
	return v, nil
}
func (f *fakePrompter) Nonzero(ctx context.Context) (string, error) {
	f.calls = append(f.calls, "nonzero")
	v := f.nonzero[0]
	f.nonzero = f.nonzero[1:]
	return v, nil
}
func (f *fakePrompter) SecretOverride(ctx context.Context, m []string) (bool, error) {
	f.calls = append(f.calls, "secret")
	v := f.secret[0]
	f.secret = f.secret[1:]
	return v, nil
}
func (f *fakePrompter) Accept(ctx context.Context, hadReadme bool, oldC, newC string) (string, error) {
	f.calls = append(f.calls, "accept")
	f.acceptCtxSnap = append(f.acceptCtxSnap, acceptSnap{hadReadme, oldC, newC})
	v := f.accept[0]
	f.accept = f.accept[1:]
	return v, nil
}

// helpers
func okGen(new string) GenerationResult {
	return GenerationResult{Status: StatusReady, NewContent: new, OldContent: "old"}
}

func TestLoop_AcceptFirstIteration(t *testing.T) {
	p := &fakePrompter{accept: []string{"a"}}
	pre := okGen("new")
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p,
		Generator: func(context.Context, string) (GenerationResult, error) {
			t.Fatal("unexpected regen")
			return GenerationResult{}, nil
		},
		Cleaner: noopCleaner,
	})
	if res.Decision != DecisionAccepted {
		t.Fatalf("got %v", res.Decision)
	}
	if len(p.calls) != 1 || p.calls[0] != "accept" {
		t.Fatalf("calls=%v", p.calls)
	}
}

func TestLoop_DiscardSkipped(t *testing.T) {
	p := &fakePrompter{accept: []string{"d"}}
	pre := okGen("new")
	cleaned := false
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p,
		Cleaner: func(context.Context, string) error { cleaned = true; return nil },
	})
	if res.Decision != DecisionSkipped || res.Reason != "user_discarded" {
		t.Fatalf("got %+v", res)
	}
	if !cleaned {
		t.Fatal("cleaner not called on skip")
	}
}

func TestLoop_Quit(t *testing.T) {
	p := &fakePrompter{accept: []string{"q"}}
	pre := okGen("new")
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionQuit {
		t.Fatalf("got %v", res.Decision)
	}
}

func TestLoop_RedoPropagatesPrevDraft(t *testing.T) {
	p := &fakePrompter{accept: []string{"r", "a"}}
	pre := okGen("draft-1")
	var seenPrev string
	gen := func(ctx context.Context, prev string) (GenerationResult, error) {
		return GenerationResult{Status: StatusReady, NewContent: "draft-2", OldContent: "old", PrevDraft: prev}, nil
	}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Generator: gen, Cleaner: noopCleaner,
		OnRedo: func(prev string) { seenPrev = prev },
	})
	if res.Decision != DecisionAccepted {
		t.Fatalf("got %v", res.Decision)
	}
	if seenPrev != "draft-1" {
		t.Fatalf("PrevDraft not propagated, got %q", seenPrev)
	}
	if len(p.acceptCtxSnap) != 2 || p.acceptCtxSnap[1].new != "draft-2" {
		t.Fatalf("second accept snap unexpected: %+v", p.acceptCtxSnap)
	}
}

func TestLoop_TimeoutRetryThenAccept(t *testing.T) {
	p := &fakePrompter{timeout: []string{"r"}, accept: []string{"a"}}
	pre := GenerationResult{Status: StatusTimeout}
	calls := 0
	gen := func(ctx context.Context, _ string) (GenerationResult, error) {
		calls++
		return okGen("ok"), nil
	}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Generator: gen, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionAccepted || calls != 1 {
		t.Fatalf("got %+v calls=%d", res, calls)
	}
}

func TestLoop_TimeoutSkip(t *testing.T) {
	p := &fakePrompter{timeout: []string{"s"}}
	pre := GenerationResult{Status: StatusTimeout}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionSkipped || res.Reason != "claude_timeout" {
		t.Fatalf("got %+v", res)
	}
}

func TestLoop_TimeoutQuit(t *testing.T) {
	p := &fakePrompter{timeout: []string{"q"}}
	pre := GenerationResult{Status: StatusTimeout}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionQuit {
		t.Fatalf("got %v", res.Decision)
	}
}

func TestLoop_NonzeroRedo(t *testing.T) {
	p := &fakePrompter{nonzero: []string{"r"}, accept: []string{"a"}}
	pre := GenerationResult{Status: StatusNonzero, Error: "exit=1"}
	gen := func(ctx context.Context, _ string) (GenerationResult, error) { return okGen("ok"), nil }
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Generator: gen, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionAccepted {
		t.Fatalf("got %v", res.Decision)
	}
}

func TestLoop_NonzeroDiscard(t *testing.T) {
	p := &fakePrompter{nonzero: []string{"d"}}
	pre := GenerationResult{Status: StatusNonzero}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionSkipped || res.Reason != "claude_nonzero_exit" {
		t.Fatalf("got %+v", res)
	}
}

func TestLoop_BlastRadiusFails(t *testing.T) {
	pre := GenerationResult{Status: StatusBlastRadius, Error: "claude_touched_other_files"}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: &fakePrompter{}, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionFailed || res.Reason != "claude_touched_other_files" {
		t.Fatalf("got %+v", res)
	}
}

func TestLoop_GenerationStatusFailed(t *testing.T) {
	pre := GenerationResult{Status: StatusFailed, Error: "kaput"}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: &fakePrompter{}, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionFailed || res.Reason != "kaput" {
		t.Fatalf("got %+v", res)
	}
}

func TestLoop_SecretOverrideAccept(t *testing.T) {
	p := &fakePrompter{secret: []bool{true}, accept: []string{"a"}}
	pre := GenerationResult{Status: StatusReady, NewContent: "new", SecretMatches: []string{"AKIA..."}}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionAccepted {
		t.Fatalf("got %v", res.Decision)
	}
}

func TestLoop_SecretOverrideRejectSkips(t *testing.T) {
	p := &fakePrompter{secret: []bool{false}}
	pre := GenerationResult{Status: StatusReady, NewContent: "new", SecretMatches: []string{"AKIA..."}}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionSkipped || res.Reason != "secrets_detected" {
		t.Fatalf("got %+v", res)
	}
}

func TestLoop_HadReadmeSetsAcceptFlag(t *testing.T) {
	p := &fakePrompter{accept: []string{"a"}}
	pre := okGen("new")
	Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, HadReadmeBefore: true, Cleaner: noopCleaner,
	})
	if len(p.acceptCtxSnap) != 1 || !p.acceptCtxSnap[0].hadReadme {
		t.Fatalf("had_readme not threaded: %+v", p.acceptCtxSnap)
	}
}

func TestLoop_RiskyFilesSkipTerminates(t *testing.T) {
	p := &fakePrompter{risky: []string{"s"}}
	pre := okGen("new")
	pre.RiskyFiles = []string{"key.pem"}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionSkipped || res.Reason != "risky_files_found" {
		t.Fatalf("got %+v", res)
	}
}

func TestLoop_RiskyFilesContinueProceeds(t *testing.T) {
	p := &fakePrompter{risky: []string{"c"}, accept: []string{"a"}}
	pre := okGen("new")
	pre.RiskyFiles = []string{"key.pem"}
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionAccepted {
		t.Fatalf("got %v", res.Decision)
	}
}

func TestLoop_CtxCancelExitsQuit(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	pre := okGen("new")
	res := Loop(ctx, SessionConfig{
		Pregenerated: &pre, Prompter: &fakePrompter{}, Cleaner: noopCleaner,
	})
	if res.Decision != DecisionQuit {
		t.Fatalf("got %v", res.Decision)
	}
}

func TestLoop_GeneratorErrorFails(t *testing.T) {
	p := &fakePrompter{accept: []string{"r"}}
	pre := okGen("d1")
	res := Loop(context.Background(), SessionConfig{
		Pregenerated: &pre, Prompter: p,
		Generator: func(context.Context, string) (GenerationResult, error) { return GenerationResult{}, errors.New("boom") },
		Cleaner:   noopCleaner,
	})
	if res.Decision != DecisionFailed {
		t.Fatalf("got %v", res.Decision)
	}
}

func noopCleaner(context.Context, string) error { return nil }
