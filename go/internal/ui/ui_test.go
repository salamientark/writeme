package ui

import (
	"testing"

	"github.com/salamientark/writeme/internal/diff"
	"github.com/salamientark/writeme/internal/selection"
)

func TestIsPrintable(t *testing.T) {
	tests := []struct {
		s    string
		want bool
	}{
		{"a", true},
		{"z", true},
		{"A", true},
		{"Z", true},
		{"1", true},
		{"!", true},
		{" ", true},
		{"", false},
		{"\x1b", false},
		{"\n", false},
		{"\t", false},
		{"aa", true}, // checks first byte only
	}
	for _, tt := range tests {
		got := isPrintable(tt.s)
		if got != tt.want {
			t.Errorf("isPrintable(%q) = %v, want %v", tt.s, got, tt.want)
		}
	}
}

func TestReviewModelRenderView(t *testing.T) {
	head := "# Old README\n"
	prev := "# Draft 1\n"
	cur := "# Draft 2\n"
	ctx := ReviewContext{
		RepoName:     "test-repo",
		Index:        1,
		Total:        5,
		HeadReadme:   &head,
		PrevDraft:    &prev,
		CurrentDraft: cur,
	}
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
	}

	if got := m.renderView("README"); got != cur {
		t.Errorf("README view = %q, want %q", got, cur)
	}

	headDiff := m.renderView("diff_head")
	if headDiff == diff.NoHeadDiff {
		t.Error("should produce real diff for head")
	}

	prevDiff := m.renderView("diff_prev")
	if prevDiff == diff.NoPrevDiff {
		t.Error("should produce real diff for prev")
	}

	if got := m.renderView("raw"); got != cur {
		t.Errorf("raw view = %q, want %q", got, cur)
	}
}

func TestReviewModelRenderViewNilHead(t *testing.T) {
	ctx := ReviewContext{
		RepoName:     "new-repo",
		Index:        1,
		Total:        1,
		HeadReadme:   nil,
		PrevDraft:    nil,
		CurrentDraft: "# First README\n",
	}
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
	}

	if got := m.renderView("diff_head"); got != diff.NoHeadDiff {
		t.Errorf("diff_head with nil head = %q, want %q", got, diff.NoHeadDiff)
	}
	if got := m.renderView("diff_prev"); got != diff.NoPrevDiff {
		t.Errorf("diff_prev with nil prev = %q, want %q", got, diff.NoPrevDiff)
	}
}

func TestReviewModelResult(t *testing.T) {
	tests := []struct {
		idx  int
		want ReviewDecision
	}{
		{-1, ReviewAccept},
		{-2, ReviewRedo},
		{-3, ReviewDiscard},
		{0, ReviewQuit},
		{3, ReviewQuit},
	}
	for _, tt := range tests {
		m := &reviewModel{viewIdx: tt.idx, offsets: make([]int, len(reviewViews))}
		got := m.Result()
		if got != tt.want {
			t.Errorf("Result() with viewIdx=%d = %q, want %q", tt.idx, got, tt.want)
		}
	}
}

func TestReviewModelLineCount(t *testing.T) {
	ctx := ReviewContext{
		RepoName:     "r",
		Index:        1,
		Total:        1,
		CurrentDraft: "line1\nline2\nline3",
	}
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
	}
	if got := m.lineCount("README"); got != 3 {
		t.Errorf("lineCount = %d, want 3", got)
	}
}

func TestReviewModelViewport(t *testing.T) {
	m := &reviewModel{height: 20}
	if got := m.viewport(); got != 16 {
		t.Errorf("viewport = %d, want 16", got)
	}
	m.height = 10
	if got := m.viewport(); got != 6 {
		t.Errorf("viewport = %d, want 6", got)
	}
	m.height = 0
	if got := m.viewport(); got != 3 {
		t.Errorf("viewport = %d, want 3", got)
	}
}

func TestSelectionResultTypes(t *testing.T) {
	r := SelectionResult{Quit: true}
	if !r.Quit {
		t.Error("Quit should be true")
	}
	if len(r.Repos) != 0 {
		t.Error("Repos should be empty")
	}

	repos := []selection.Repo{{Name: "a"}, {Name: "b"}}
	r2 := SelectionResult{Repos: repos}
	if len(r2.Repos) != 2 {
		t.Errorf("Repos len = %d", len(r2.Repos))
	}
}
