package commit

import (
	"bufio"
	"bytes"
	"context"
	"strings"
	"testing"
	"time"
)

func TestPromptModeAllChoices(t *testing.T) {
	cases := map[string]Mode{"p\n": ModePR, "m\n": ModeDirect, "c\n": ModeCommitOnly, "n\n": ModeSkip}
	for in, want := range cases {
		r := bufio.NewReader(strings.NewReader(in))
		if got := PromptMode(context.Background(), r, &bytes.Buffer{}); got != want {
			t.Errorf("in=%q got=%q want=%q", in, got, want)
		}
	}
}

func TestPromptModeRetry(t *testing.T) {
	r := bufio.NewReader(strings.NewReader("xx\np\n"))
	if got := PromptMode(context.Background(), r, &bytes.Buffer{}); got != ModePR {
		t.Errorf("got %q", got)
	}
}

func TestPromptModeEOF(t *testing.T) {
	r := bufio.NewReader(strings.NewReader(""))
	if got := PromptMode(context.Background(), r, &bytes.Buffer{}); got != ModeSkip {
		t.Errorf("got %q", got)
	}
}

func TestPromptModeCtxCancel(t *testing.T) {
	pr, pw := bufio.NewReader(strings.NewReader("")), bytes.Buffer{}
	_ = pw
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan Mode, 1)
	go func() { done <- PromptMode(ctx, pr, &bytes.Buffer{}) }()
	time.Sleep(10 * time.Millisecond)
	cancel()
	select {
	case m := <-done:
		if m != ModeSkip {
			t.Errorf("got %q", m)
		}
	case <-time.After(time.Second):
		t.Fatal("ctx cancel did not unblock PromptMode")
	}
}
