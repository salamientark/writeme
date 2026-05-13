package ui

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

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
		decision ReviewDecision
		want     ReviewDecision
	}{
		{ReviewAccept, ReviewAccept},
		{ReviewRedo, ReviewRedo},
		{ReviewDiscard, ReviewDiscard},
		{"", ReviewQuit},
	}
	for _, tt := range tests {
		m := &reviewModel{decision: tt.decision, offsets: make([]int, len(reviewViews))}
		got := m.Result()
		if got != tt.want {
			t.Errorf("Result() with decision=%q = %q, want %q", tt.decision, got, tt.want)
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

// --- selectionModel tests ---

func TestSelectionModelInit(t *testing.T) {
	m := &selectionModel{
		state: selection.NewSelectionState([]selection.Repo{{Name: "a"}}, 0, nil, 0, 15),
	}
	if cmd := m.Init(); cmd != nil {
		t.Errorf("Init() should return nil, got %v", cmd)
	}
}

func TestSelectionModelUpdateWindowResize(t *testing.T) {
	m := &selectionModel{
		state: selection.NewSelectionState([]selection.Repo{{Name: "a"}}, 0, nil, 0, 15),
	}
	_, cmd := m.Update(tea.WindowSizeMsg{Width: 80, Height: 24})
	if cmd != nil {
		t.Errorf("unexpected cmd: %v", cmd)
	}
	if m.width != 80 {
		t.Errorf("width = %d, want 80", m.width)
	}
	if m.height != 24 {
		t.Errorf("height = %d, want 24", m.height)
	}
}

func TestSelectionModelUpdateWindowResizeSmall(t *testing.T) {
	m := &selectionModel{
		state: selection.NewSelectionState([]selection.Repo{{Name: "a"}}, 0, nil, 0, 15),
	}
	// Height 10 → viewport = 10-6 = 4 → clamped to 5
	m.Update(tea.WindowSizeMsg{Width: 80, Height: 10})
	if m.state.ViewportHeight != 5 {
		t.Errorf("viewportHeight = %d, want 5 (clamped min)", m.state.ViewportHeight)
	}
}

func TestSelectionModelUpdateFilterMode(t *testing.T) {
	repos := []selection.Repo{{Name: "alpha"}, {Name: "beta"}, {Name: "gamma"}}
	st := selection.NewSelectionState(repos, 0, nil, 0, 15)
	m := &selectionModel{state: st, filterMode: true}
	// esc exits filter mode
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyEscape})
	if cmd != nil {
		t.Errorf("unexpected cmd: %v", cmd)
	}
	if m.filterMode {
		t.Error("filterMode should be false after esc")
	}
}

func TestSelectionModelUpdateNormalMode(t *testing.T) {
	repos := []selection.Repo{{Name: "a"}, {Name: "b"}, {Name: "c"}}
	st := selection.NewSelectionState(repos, 0, nil, 0, 15)
	m := &selectionModel{state: st, filterMode: false}

	// / enters filter mode
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	if !m.filterMode {
		t.Error("filterMode should be true after /")
	}
	if m.filterBuf != "" {
		t.Errorf("filterBuf = %q, want empty", m.filterBuf)
	}

	// q quits
	m.filterMode = false
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'q'}})
	if cmd == nil {
		t.Error("q should return tea.Quit")
	}
}

func TestSelectionModelHandleFilterKey(t *testing.T) {
	repos := []selection.Repo{{Name: "alpha"}, {Name: "beta"}}
	st := selection.NewSelectionState(repos, 0, nil, 0, 15)
	m := &selectionModel{state: st, filterMode: true}

	// Type a filter character
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'a'}})
	if m.filterBuf != "a" {
		t.Errorf("filterBuf = %q, want 'a'", m.filterBuf)
	}

	// Type another character
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'l'}})
	if m.filterBuf != "al" {
		t.Errorf("filterBuf = %q, want 'al'", m.filterBuf)
	}

	// Backspace
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyBackspace})
	if m.filterBuf != "a" {
		t.Errorf("filterBuf = %q after backspace, want 'a'", m.filterBuf)
	}

	// Backspace on empty
	m.filterBuf = ""
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyBackspace})
	if m.filterBuf != "" {
		t.Error("filterBuf should stay empty")
	}

	// Enter exits filter mode
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyEnter})
	if m.filterMode {
		t.Error("filterMode should be false after enter")
	}

	// Esc exits filter mode
	m.filterMode = true
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyEscape})
	if m.filterMode {
		t.Error("filterMode should be false after esc")
	}
}

func TestSelectionModelHandleFilterKeyIgnoresNonPrintable(t *testing.T) {
	repos := []selection.Repo{{Name: "alpha"}}
	st := selection.NewSelectionState(repos, 0, nil, 0, 15)
	m := &selectionModel{state: st, filterMode: true, filterBuf: "before"}

	// Tab is not printable (ASCII 9)
	m.handleFilterKey(tea.KeyMsg{Type: tea.KeyTab})
	if m.filterBuf != "before" {
		t.Errorf("non-printable key should not change filterBuf, got %q", m.filterBuf)
	}
}

func TestSelectionModelHandleNormalKeyAllKeys(t *testing.T) {
	repos := make([]selection.Repo, 20)
	for i := range repos {
		repos[i] = selection.Repo{Name: string(rune('a' + (i % 26)))}
	}
	st := selection.NewSelectionState(repos, 5, nil, 0, 15)
	m := &selectionModel{state: st}

	// up / k → move cursor up
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyUp})
	if cmd != nil {
		t.Errorf("unexpected quit from up: %v", cmd)
	}
	if m.state.Cursor != 4 {
		t.Errorf("cursor after up = %d, want 4", m.state.Cursor)
	}

	// down / j → move cursor down
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'j'}})
	if m.state.Cursor != 5 {
		t.Errorf("cursor after 'j' = %d, want 5", m.state.Cursor)
	}

	// space → toggle
	wasSelected := m.state.IsSelected(5)
	m.Update(tea.KeyMsg{Type: tea.KeySpace, Runes: []rune{' '}})
	if m.state.IsSelected(5) == wasSelected {
		t.Error("toggle didn't change selection")
	}

	// a → select all visible
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'a'}})
	for i := 0; i < 15; i++ {
		if !m.state.IsSelected(i) {
			t.Errorf("select-all missed index %d", i)
		}
	}

	// n → select none visible
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'n'}})
	for i := 0; i < 15; i++ {
		if m.state.IsSelected(i) {
			t.Errorf("select-none should have cleared index %d", i)
		}
	}

	// g → jump to top
	m.state = selection.NewSelectionState(repos, 10, nil, 0, 15)
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'g'}})
	if m.state.Cursor != 0 {
		t.Errorf("cursor after g = %d, want 0", m.state.Cursor)
	}

	// G → jump to bottom
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'G'}})
	if m.state.Cursor != 19 {
		t.Errorf("cursor after G = %d, want 19", m.state.Cursor)
	}

	// pgup → page up
	st2 := selection.NewSelectionState(repos, 18, nil, 0, 15)
	m.state = st2
	m.Update(tea.KeyMsg{Type: tea.KeyPgUp})
	if m.state.Cursor >= 18 {
		t.Errorf("cursor after pgup = %d, should have moved up", m.state.Cursor)
	}

	// pgdown → page down
	m.state = selection.NewSelectionState(repos, 0, nil, 0, 15)
	m.Update(tea.KeyMsg{Type: tea.KeyPgDown})
	if m.state.Cursor <= 0 {
		t.Errorf("cursor after pgdown = %d, should have moved down", m.state.Cursor)
	}

	// s → toggle solo only
	m.state = selection.NewSelectionState(repos, 0, nil, 0, 15)
	wasSolo := m.state.SoloOnly
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'s'}})
	if m.state.SoloOnly == wasSolo {
		t.Error("s should toggle SoloOnly")
	}

	// F → toggle exclude forks
	wasExcludeForks := m.state.ExcludeForks
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'F'}})
	if m.state.ExcludeForks == wasExcludeForks {
		t.Error("F should toggle ExcludeForks")
	}

	// r → toggle exclude existing readme
	wasExcludeReadme := m.state.ExcludeExistingReadme
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}})
	if m.state.ExcludeExistingReadme == wasExcludeReadme {
		t.Error("r should toggle ExcludeExistingReadme")
	}
}

func TestSelectionModelViewLoading(t *testing.T) {
	m := &selectionModel{width: 0}
	got := m.View()
	if !strings.Contains(got, "loading...") {
		t.Errorf("View() with width=0 should show loading, got %q", got)
	}
}

func TestSelectionModelViewNormal(t *testing.T) {
	repos := []selection.Repo{
		{Name: "repo-one"},
		{Name: "repo-two"},
		{Name: "repo-three-is-very-long-and-should-be-truncated"},
		{Name: "fork-repo", IsFork: true},
		{Name: "existing-readme", HadReadmeBefore: true},
	}
	sel := map[int]bool{0: true, 4: true}
	st := selection.NewSelectionState(repos, 0, sel, 0, 15)
	m := &selectionModel{state: st, width: 80, height: 30}

	got := m.View()
	if !strings.Contains(got, "repo-one") {
		t.Error("View should contain repo-one")
	}
	if !strings.Contains(got, "[x]") {
		t.Error("View should show selected checkmarks")
	}
	if !strings.Contains(got, "FORK") {
		t.Error("View should show FORK flag")
	}
	if !strings.Contains(got, "README") {
		t.Error("View should show README flag")
	}
	if !strings.Contains(got, "arrows move") {
		t.Error("View should show footer")
	}
	// Long name should be truncated
	if strings.Contains(got, "repo-three-is-very-long-and-should-be-truncated") {
		t.Error("long name should be truncated")
	}
}

func TestSelectionModelViewFilterMode(t *testing.T) {
	repos := []selection.Repo{{Name: "alpha"}, {Name: "beta"}}
	st := selection.NewSelectionState(repos, 0, nil, 0, 15)
	m := &selectionModel{state: st, width: 80, height: 30, filterMode: true, filterBuf: "al"}

	got := m.View()
	if !strings.Contains(got, "filter: al_") {
		t.Errorf("View in filter mode should show filter prompt, got %q", got)
	}
}

func TestSelectionModelViewToggles(t *testing.T) {
	repos := []selection.Repo{{Name: "a"}}
	st := selection.NewSelectionState(repos, 0, nil, 0, 15)
	// Enable all toggles
	st.SoloOnly = true
	st.ExcludeForks = true
	st.ExcludeExistingReadme = true
	m := &selectionModel{state: st, width: 80, height: 30}

	got := m.View()
	if !strings.Contains(got, "solo") {
		t.Error("View should show solo in toggles")
	}
	if !strings.Contains(got, "no-forks") {
		t.Error("View should show no-forks in toggles")
	}
	if !strings.Contains(got, "no-readme") {
		t.Error("View should show no-readme in toggles")
	}
}

// --- reviewModel tests ---

func TestReviewModelInit(t *testing.T) {
	ctx := ReviewContext{RepoName: "r", Index: 1, Total: 1, CurrentDraft: "draft"}
	m := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}
	if cmd := m.Init(); cmd != nil {
		t.Errorf("Init() should return nil, got %v", cmd)
	}
}

func TestReviewModelUpdateWindowResize(t *testing.T) {
	ctx := ReviewContext{RepoName: "r", Index: 1, Total: 1, CurrentDraft: "draft"}
	m := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}
	m.Update(tea.WindowSizeMsg{Width: 100, Height: 40})
	if m.width != 100 {
		t.Errorf("width = %d", m.width)
	}
	if m.height != 40 {
		t.Errorf("height = %d", m.height)
	}
}

func TestReviewModelUpdateKeyBindings(t *testing.T) {
	// Create content with enough lines to exceed viewport (height=6 → viewport=3).
	// 20 lines of content → plenty of room to scroll.
	lines := make([]string, 20)
	for i := range lines {
		lines[i] = "line content " + string(rune('a'+i%26))
	}
	ctx := ReviewContext{
		RepoName:     "test-repo",
		Index:        1,
		Total:        5,
		CurrentDraft: strings.Join(lines, "\n"),
	}
	m := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews)), height: 6}

	// tab cycles views
	m.Update(tea.KeyMsg{Type: tea.KeyTab})
	if m.viewIdx != 1 {
		t.Errorf("viewIdx after tab = %d, want 1", m.viewIdx)
	}
	m.Update(tea.KeyMsg{Type: tea.KeyTab})
	if m.viewIdx != 2 {
		t.Errorf("viewIdx after 2nd tab = %d, want 2", m.viewIdx)
	}

	// 1 switches to diff_head
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'1'}})
	if m.viewIdx != 1 {
		t.Errorf("viewIdx after 1 = %d, want 1", m.viewIdx)
	}

	// 2 switches to diff_prev
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'2'}})
	if m.viewIdx != 2 {
		t.Errorf("viewIdx after 2 = %d, want 2", m.viewIdx)
	}

	// v switches to raw
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'v'}})
	if m.viewIdx != 3 {
		t.Errorf("viewIdx after v = %d, want 3", m.viewIdx)
	}

	// j scrolls down
	m.viewIdx = 0
	m.offsets[0] = 0
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'j'}})
	if m.offsets[0] != 1 {
		t.Errorf("offset after j = %d, want 1", m.offsets[0])
	}

	// k scrolls up
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'k'}})
	if m.offsets[0] != 0 {
		t.Errorf("offset after k = %d, want 0", m.offsets[0])
	}

	// k at 0 stays at 0
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'k'}})
	if m.offsets[0] != 0 {
		t.Errorf("offset after k at top = %d, want 0", m.offsets[0])
	}

	// down alias
	m.offsets[0] = 0
	m.Update(tea.KeyMsg{Type: tea.KeyDown})
	if m.offsets[0] != 1 {
		t.Errorf("offset after down = %d, want 1", m.offsets[0])
	}

	// up alias
	m.offsets[0] = 2
	m.Update(tea.KeyMsg{Type: tea.KeyUp})
	if m.offsets[0] != 1 {
		t.Errorf("offset after up = %d, want 1", m.offsets[0])
	}

	// g goes to top
	m.offsets[0] = 5
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'g'}})
	if m.offsets[0] != 0 {
		t.Errorf("offset after g = %d, want 0", m.offsets[0])
	}

	// G goes to bottom
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'G'}})
	bottomWant := 20 - m.viewport()
	if m.offsets[0] != bottomWant {
		t.Errorf("offset after G = %d, want %d (bottom)", m.offsets[0], bottomWant)
	}

	// pgdown scrolls down a page
	m.offsets[0] = 0
	m.Update(tea.KeyMsg{Type: tea.KeyPgDown})
	if m.offsets[0] == 0 {
		t.Error("pgdown should scroll down")
	}

	// pgup scrolls up a page
	pgUpInitial := m.offsets[0]
	m.Update(tea.KeyMsg{Type: tea.KeyPgUp})
	if m.offsets[0] >= pgUpInitial {
		t.Error("pgup should scroll up from non-zero position")
	}

	// space scrolls down (like pgdown)
	m.offsets[0] = 0
	m.Update(tea.KeyMsg{Type: tea.KeySpace, Runes: []rune{' '}})
	if m.offsets[0] == 0 {
		t.Error("space should scroll down")
	}

	// b scrolls up (like pgup)
	bInit := m.offsets[0]
	m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'b'}})
	if m.offsets[0] >= bInit {
		t.Error("b should scroll up from non-zero position")
	}
}

func TestReviewModelUpdateDecisionKeys(t *testing.T) {
	ctx := ReviewContext{RepoName: "r", Index: 1, Total: 1, CurrentDraft: "d"}
	m := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}

	// a → accept
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'a'}})
	if cmd == nil {
		t.Error("a should return tea.Quit")
	}
	if m.decision != ReviewAccept {
		t.Errorf("decision after a = %q, want %q", m.decision, ReviewAccept)
	}
	if m.Result() != ReviewAccept {
		t.Error("should be accept")
	}

	// r → redo
	m2 := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}
	m2.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}})
	if m2.Result() != ReviewRedo {
		t.Error("should be redo")
	}

	// d → discard
	m3 := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}
	m3.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'d'}})
	if m3.Result() != ReviewDiscard {
		t.Error("should be discard")
	}

	// q → quit
	m4 := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}
	_, cmd4 := m4.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'q'}})
	if cmd4 == nil {
		t.Error("q should return tea.Quit")
	}
	// decision stays "", so Result() returns ReviewQuit
	if m4.Result() != ReviewQuit {
		t.Error("should be quit")
	}

	// ctrl+c → quit
	m5 := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews))}
	_, cmd5 := m5.Update(tea.KeyMsg{Type: tea.KeyCtrlC})
	if cmd5 == nil {
		t.Error("ctrl+c should return tea.Quit")
	}
}

func TestReviewModelUpdateMouseWheel(t *testing.T) {
	ctx := ReviewContext{RepoName: "r", Index: 1, Total: 1, CurrentDraft: "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk\nl\nm\nn\no\np\nq\nr\ns\nt\nu\nv\nw\nx\ny\nz"}
	m := &reviewModel{ctx: ctx, offsets: make([]int, len(reviewViews)), height: 10}

	// Wheel down
	m.Update(tea.MouseMsg{Button: tea.MouseButtonWheelDown})
	if m.offsets[0] != 3 {
		t.Errorf("offset after wheel down = %d, want 3", m.offsets[0])
	}

	// Wheel up
	m.Update(tea.MouseMsg{Button: tea.MouseButtonWheelUp})
	if m.offsets[0] != 0 {
		t.Errorf("offset after wheel up = %d, want 0", m.offsets[0])
	}

	// Wheel up at 0 stays at 0
	m.Update(tea.MouseMsg{Button: tea.MouseButtonWheelUp})
	if m.offsets[0] != 0 {
		t.Error("wheel up at top should stay 0")
	}
}

func TestReviewModelViewLoading(t *testing.T) {
	m := &reviewModel{offsets: make([]int, len(reviewViews)), width: 0, height: 0}
	got := m.View()
	if !strings.Contains(got, "loading...") {
		t.Errorf("View() with zero dimensions should show loading, got %q", got)
	}
}

func TestReviewModelViewNormal(t *testing.T) {
	ctx := ReviewContext{
		RepoName:     "my-repo",
		Index:        2,
		Total:        10,
		CurrentDraft: "# Title\n\nSome content here.\n",
	}
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
		width:   80,
		height:  24,
	}

	got := m.View()
	if !strings.Contains(got, "my-repo") {
		t.Error("View should contain repo name")
	}
	if !strings.Contains(got, "[2/10]") {
		t.Error("View should contain index/total")
	}
	if !strings.Contains(got, "accept") {
		t.Error("View should show accept hint")
	}
	if !strings.Contains(got, "# Title") {
		t.Error("View should show draft content")
	}
}

func TestReviewModelViewEmpty(t *testing.T) {
	ctx := ReviewContext{
		RepoName:     "empty-repo",
		Index:        1,
		Total:        1,
		CurrentDraft: "",
	}
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
		width:   80,
		height:  24,
	}

	got := m.View()
	if !strings.Contains(got, "empty") {
		t.Error("View with empty content should show 'empty'")
	}
}

func TestSelectionModelViewHiddenSelected(t *testing.T) {
	repos := []selection.Repo{
		{Name: "visible-alpha"},
		{Name: "visible-beta"},
		{Name: "hidden-gamma"},
	}
	sel := map[int]bool{2: true} // only the hidden one selected
	st := selection.NewSelectionState(repos, 0, sel, 0, 15)
	// Apply filter so gamma is hidden
	st = st.WithFilter("visible")
	m := &selectionModel{state: st, width: 80, height: 30}

	got := m.View()
	if !strings.Contains(got, "1 hidden") {
		t.Errorf("View should show hidden count, got %q", got)
	}
}

func TestRenderMarkdown(t *testing.T) {
	tests := []struct {
		name  string
		src   string
		width int
	}{
		{"narrow clamps to 80", "# Hello\n\nbody text", 5},
		{"normal width", "# Title\n\nparagraph", 80},
		{"empty input", "", 80},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := renderMarkdown(tt.src, tt.width)
			// Non-empty input should produce non-empty output.
			if tt.src != "" && got == "" {
				t.Errorf("renderMarkdown(%q, %d) returned empty", tt.src, tt.width)
			}
			// Output must not have trailing newline (TrimRight'd).
			if strings.HasSuffix(got, "\n") {
				t.Error("output should not end with newline")
			}
		})
	}
}

func TestColorizeDiff(t *testing.T) {
	src := "--- a\n+++ b\n@@ -1,1 +1,1 @@\n-old line\n+new line\n context line"
	got := colorizeDiff(src)
	if got == "" {
		t.Fatal("colorizeDiff returned empty")
	}
	if !strings.Contains(got, "old line") {
		t.Error("output should contain deleted line text")
	}
	if !strings.Contains(got, "new line") {
		t.Error("output should contain added line text")
	}
	if !strings.Contains(got, "context line") {
		t.Error("output should contain context line text")
	}
	if !strings.Contains(got, "@@") {
		t.Error("output should contain hunk marker")
	}
	if strings.HasSuffix(got, "\n") {
		t.Error("output should not end with newline")
	}
}

func TestColorizeDiffEmpty(t *testing.T) {
	got := colorizeDiff("")
	if got != "" {
		t.Errorf("colorizeDiff(\"\") = %q, want empty", got)
	}
}

func TestRenderViewWithWidthCaches(t *testing.T) {
	head := "# Old\n"
	prev := "# Prev\n"
	ctx := ReviewContext{
		RepoName:     "r",
		Index:        1,
		Total:        1,
		HeadReadme:   &head,
		PrevDraft:    &prev,
		CurrentDraft: "# New README\n\nbody",
	}
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
		width:   80,
		height:  24,
	}

	// First call populates cache for each view.
	first := m.renderView("README")
	if first == "" {
		t.Fatal("rendered README empty")
	}
	if _, ok := m.renderCache["README"]; !ok {
		t.Error("README should be cached")
	}

	// Second call hits the cache (same result).
	second := m.renderView("README")
	if first != second {
		t.Error("cached render should be stable")
	}

	// diff_head/diff_prev/raw all populate cache.
	m.renderView("diff_head")
	m.renderView("diff_prev")
	m.renderView("raw")
	for _, v := range []string{"diff_head", "diff_prev", "raw"} {
		if _, ok := m.renderCache[v]; !ok {
			t.Errorf("%s not cached", v)
		}
	}

	// Width change invalidates cache.
	m.width = 120
	m.renderView("README")
	if m.cacheWidth != 120-4 {
		t.Errorf("cacheWidth = %d, want %d", m.cacheWidth, 120-4)
	}
}

func TestRenderViewTinyWidthClamps(t *testing.T) {
	ctx := ReviewContext{
		RepoName:     "r",
		Index:        1,
		Total:        1,
		CurrentDraft: "# X",
	}
	// width=10 → contentWidth=6 → clamped to 80 inside renderView
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
		width:   10,
		height:  24,
	}
	got := m.renderView("README")
	if got == "" {
		t.Error("renderView should not be empty for tiny width")
	}
	if m.cacheWidth != 80 {
		t.Errorf("cacheWidth = %d, want 80 (clamped)", m.cacheWidth)
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
