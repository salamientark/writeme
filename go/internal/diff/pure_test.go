package diff

import (
	"strings"
	"testing"
)

func TestUnified_Changes(t *testing.T) {
	out := Unified("a\nb\nc\n", "a\nB\nc\n", "x", "y")
	if !strings.Contains(out, "--- x") {
		t.Errorf("missing --- x in %q", out)
	}
	if !strings.Contains(out, "+++ y") {
		t.Errorf("missing +++ y in %q", out)
	}
	if !strings.Contains(out, "-b") {
		t.Errorf("missing -b in %q", out)
	}
	if !strings.Contains(out, "+B") {
		t.Errorf("missing +B in %q", out)
	}
}

func TestUnified_Identical(t *testing.T) {
	out := Unified("same\n", "same\n", "a", "b")
	if out != NoChanges {
		t.Errorf("got %q, want %q", out, NoChanges)
	}
}

func TestUnified_MissingTrailingNewline(t *testing.T) {
	out := Unified("a\nb", "a\nc", "x", "y")
	if !strings.Contains(out, "-b") {
		t.Errorf("missing -b in %q", out)
	}
	if !strings.Contains(out, "+c") {
		t.Errorf("missing +c in %q", out)
	}
}

func TestDiffVsHead_NoHead(t *testing.T) {
	out := DiffVsHead(nil, "new draft\n")
	if out != NoHeadDiff {
		t.Errorf("got %q, want %q", out, NoHeadDiff)
	}
}

func TestDiffVsHead_EmptyHead(t *testing.T) {
	old := ""
	out := DiffVsHead(&old, "new draft\n")
	if out == NoHeadDiff {
		t.Error("should not return fallback for empty (not nil) head")
	}
	if !strings.Contains(out, "+new draft") {
		t.Errorf("missing +new draft in %q", out)
	}
}

func TestDiffVsHead_RealDiff(t *testing.T) {
	old := "old\n"
	out := DiffVsHead(&old, "new\n")
	if !strings.Contains(out, "README.md (HEAD)") {
		t.Errorf("missing HEAD label in %q", out)
	}
	if !strings.Contains(out, "README.md (draft)") {
		t.Errorf("missing draft label in %q", out)
	}
	if !strings.Contains(out, "-old") {
		t.Errorf("missing -old in %q", out)
	}
	if !strings.Contains(out, "+new") {
		t.Errorf("missing +new in %q", out)
	}
}

func TestDiffVsPrev_NoPrev(t *testing.T) {
	out := DiffVsPrev(nil, "new\n")
	if out != NoPrevDiff {
		t.Errorf("got %q, want %q", out, NoPrevDiff)
	}
}

func TestDiffVsPrev_EmptyPrev(t *testing.T) {
	prev := ""
	out := DiffVsPrev(&prev, "new\n")
	if out == NoPrevDiff {
		t.Error("should not return fallback for empty (not nil) prev")
	}
	if !strings.Contains(out, "+new") {
		t.Errorf("missing +new in %q", out)
	}
}

func TestDiffVsPrev_RealDiff(t *testing.T) {
	prev := "draft1\n"
	out := DiffVsPrev(&prev, "draft2\n")
	if !strings.Contains(out, "README.md (prev draft)") {
		t.Errorf("missing prev draft label in %q", out)
	}
	if !strings.Contains(out, "README.md (draft)") {
		t.Errorf("missing draft label in %q", out)
	}
}
