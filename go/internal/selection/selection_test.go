package selection

import (
	"bytes"
	"strings"
	"testing"

	"github.com/salamientark/writeme/internal/fetch"
)

func TestRenderPlain(t *testing.T) {
	var buf bytes.Buffer
	RenderPlain(&buf, []fetch.Repo{{Name: "a"}, {Name: "b"}})
	out := buf.String()
	if !strings.Contains(out, "1  a") || !strings.Contains(out, "2  b") {
		t.Errorf("got %q", out)
	}
}

func TestPromptOK(t *testing.T) {
	in := strings.NewReader("1,3-4\n")
	var out bytes.Buffer
	got, err := Prompt(in, &out, 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 || got[0] != 0 || got[2] != 3 {
		t.Errorf("got %v", got)
	}
}

func TestPromptAll(t *testing.T) {
	got, err := Prompt(strings.NewReader("a\n"), &bytes.Buffer{}, 3)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Errorf("got %v", got)
	}
}

func TestPromptQuit(t *testing.T) {
	got, err := Prompt(strings.NewReader("\n"), &bytes.Buffer{}, 3)
	if err != nil {
		t.Fatal(err)
	}
	if got != nil {
		t.Errorf("got %v", got)
	}
}

func TestPromptRetryOnError(t *testing.T) {
	in := strings.NewReader("foo\n2\n")
	var out bytes.Buffer
	got, err := Prompt(in, &out, 3)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0] != 1 {
		t.Errorf("got %v", got)
	}
	if !strings.Contains(out.String(), "bad token") {
		t.Errorf("missing error msg: %q", out.String())
	}
}

func TestPromptEOF(t *testing.T) {
	if _, err := Prompt(strings.NewReader(""), &bytes.Buffer{}, 1); err == nil {
		t.Error("want err")
	}
}
