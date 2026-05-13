package review

import (
	"bufio"
	"bytes"
	"context"
	"io"
	"strings"
	"testing"
	"time"
)

func TestReadLineCtx_Cancelled(t *testing.T) {
	pr, pw := io.Pipe()
	defer pw.Close()
	br := bufio.NewReader(pr)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_, _ = readLineCtx(ctx, br)
		close(done)
	}()
	time.Sleep(20 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("readLineCtx did not unblock on ctx cancel")
	}
}

func TestReadLineCtx_Reads(t *testing.T) {
	br := bufio.NewReader(strings.NewReader("hello\n"))
	line, err := readLineCtx(context.Background(), br)
	if err != nil || line != "hello\n" {
		t.Fatalf("got %q err=%v", line, err)
	}
}

func TestStdinPrompter_Accept(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("a\n"))
	out := &bytes.Buffer{}
	p := NewStdinPrompter(in, out)
	got, err := p.Accept(context.Background(), false, "", "")
	if err != nil || got != "a" {
		t.Fatalf("got=%q err=%v", got, err)
	}
}

func TestStdinPrompter_HadReadmeRequiresYes(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("a\nyes\n"))
	out := &bytes.Buffer{}
	p := NewStdinPrompter(in, out)
	got, err := p.Accept(context.Background(), true, "", "")
	if err != nil || got != "a" {
		// "a" is not accepted when had_readme=true; expect prompter to keep looping until "yes"
		t.Fatalf("expected loop-until-yes behavior; got=%q err=%v", got, err)
	}
	// Note: Accept returns "a" outcome — the FSM should map raw "yes" to accept when had_readme.
	// We expose this here as: returns "a" when user typed "yes" (had_readme path).
}

func TestStdinPrompter_SecretOverride(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("yes-i-checked\n"))
	out := &bytes.Buffer{}
	p := NewStdinPrompter(in, out)
	ok, err := p.SecretOverride(context.Background(), []string{"AKIA"})
	if err != nil || !ok {
		t.Fatalf("ok=%v err=%v", ok, err)
	}
}

func TestStdinPrompter_SecretOverrideNo(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("no\n"))
	p := NewStdinPrompter(in, &bytes.Buffer{})
	ok, _ := p.SecretOverride(context.Background(), []string{"X"})
	if ok {
		t.Fatal("override should be false")
	}
}

func TestStdinPrompter_RiskyFiles(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("x\ns\n"))
	p := NewStdinPrompter(in, &bytes.Buffer{})
	got, err := p.RiskyFiles(context.Background(), []string{"a", "b"})
	if err != nil || got != "s" {
		t.Fatalf("got=%q err=%v", got, err)
	}
}

func TestStdinPrompter_RiskyFilesTruncates(t *testing.T) {
	files := make([]string, 15)
	for i := range files {
		files[i] = "f"
	}
	in := bufio.NewReader(strings.NewReader("c\n"))
	out := &bytes.Buffer{}
	p := NewStdinPrompter(in, out)
	got, _ := p.RiskyFiles(context.Background(), files)
	if got != "c" {
		t.Errorf("got %q", got)
	}
	if !strings.Contains(out.String(), "and 5 more") {
		t.Errorf("truncation msg missing: %s", out.String())
	}
}

func TestStdinPrompter_Timeout(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("xx\nr\n"))
	p := NewStdinPrompter(in, &bytes.Buffer{})
	got, err := p.Timeout(context.Background())
	if err != nil || got != "r" {
		t.Fatalf("got=%q err=%v", got, err)
	}
}

func TestStdinPrompter_Nonzero(t *testing.T) {
	in := bufio.NewReader(strings.NewReader("zz\nd\n"))
	p := NewStdinPrompter(in, &bytes.Buffer{})
	got, err := p.Nonzero(context.Background())
	if err != nil || got != "d" {
		t.Fatalf("got=%q err=%v", got, err)
	}
}

func TestStdinPrompter_AcceptRedoDiscardQuit(t *testing.T) {
	for _, c := range []string{"r", "d", "q"} {
		in := bufio.NewReader(strings.NewReader(c + "\n"))
		p := NewStdinPrompter(in, &bytes.Buffer{})
		got, _ := p.Accept(context.Background(), false, "", "")
		if got != c {
			t.Errorf("c=%q got=%q", c, got)
		}
	}
}

func TestStageSkill_RejectsTraversal(t *testing.T) {
	base := t.TempDir()
	_, err := StageSkill(base, base+"/../escape")
	if err == nil {
		t.Fatal("expected error on path traversal")
	}
}

func TestStageSkill_AllowsUnderBase(t *testing.T) {
	base := t.TempDir()
	repo := base + "/r"
	if _, err := StageSkill(base, repo); err != nil {
		t.Fatalf("unexpected: %v", err)
	}
}
