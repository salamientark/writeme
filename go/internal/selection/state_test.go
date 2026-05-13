package selection

import (
	"fmt"
	"testing"
)

// Helpers

func makeRepos(n int) []Repo {
	repos := make([]Repo, n)
	for i := 0; i < n; i++ {
		repos[i] = Repo{
			Name:            fmt.Sprintf("repo-%d", i),
			SSHURL:          fmt.Sprintf("git@github.com:user/repo-%d.git", i),
			PushedAt:        "2026-01-01T00:00:00Z",
			HadReadmeBefore: i%2 == 0,
			DiskUsage:       100 * (i + 1),
		}
	}
	return repos
}

func makeState(n int, viewportHeight int) *SelectionState {
	repos := makeRepos(n)
	return NewSelectionState(repos, 0, nil, 0, viewportHeight)
}

// TestRepoStruct verifies Repo fields are accessible and struct is usable.
func TestRepoStruct_FieldsAccessible(t *testing.T) {
	r := Repo{
		Name:            "my-repo",
		SSHURL:          "git@github.com:x/my-repo.git",
		PushedAt:        "2026-04-01T12:00:00Z",
		HadReadmeBefore: true,
		DiskUsage:       512,
	}
	if r.Name != "my-repo" {
		t.Errorf("Name = %q", r.Name)
	}
	if r.SSHURL != "git@github.com:x/my-repo.git" {
		t.Errorf("SSHURL = %q", r.SSHURL)
	}
	if r.PushedAt != "2026-04-01T12:00:00Z" {
		t.Errorf("PushedAt = %q", r.PushedAt)
	}
	if !r.HadReadmeBefore {
		t.Error("HadReadmeBefore should be true")
	}
	if r.DiskUsage != 512 {
		t.Errorf("DiskUsage = %d", r.DiskUsage)
	}
}

// TestSelectionStateConstruction verifies initial state values.
func TestSelectionStateConstruction_InitialCursorZero(t *testing.T) {
	s := makeState(3, 5)
	if s.Cursor != 0 {
		t.Errorf("cursor = %d", s.Cursor)
	}
}

func TestSelectionStateConstruction_InitialSelectedEmpty(t *testing.T) {
	s := makeState(3, 5)
	if len(s.Selected) != 0 {
		t.Errorf("selected len = %d", len(s.Selected))
	}
}

func TestSelectionStateConstruction_ReposStored(t *testing.T) {
	s := makeState(3, 5)
	if len(s.Repos) != 3 {
		t.Errorf("repos len = %d", len(s.Repos))
	}
	if s.Repos[0].Name != "repo-0" {
		t.Errorf("repos[0].Name = %q", s.Repos[0].Name)
	}
}

// TestToggle verifies toggle flips cursor index in selected.
func TestToggle_SelectsUnselectedCursor(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.Toggle()
	if !s2.IsSelected(0) {
		t.Error("expected cursor 0 to be selected")
	}
}

func TestToggle_DeselectsAlreadySelectedCursor(t *testing.T) {
	s := NewSelectionState(makeRepos(3), 1, map[int]bool{1: true}, 0, 5)
	s2 := s.Toggle()
	if s2.IsSelected(1) {
		t.Error("expected cursor 1 to be deselected")
	}
}

func TestToggle_ReturnsNewInstance(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.Toggle()
	if s == s2 {
		t.Error("expected new instance")
	}
	if len(s.Selected) != 0 {
		t.Error("original should not be mutated")
	}
}

func TestToggle_DoesNotChangeCursor(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.Toggle()
	if s2.Cursor != s.Cursor {
		t.Errorf("cursor changed from %d to %d", s.Cursor, s2.Cursor)
	}
}

func TestToggle_EmptyReposDoesNothing(t *testing.T) {
	s := NewSelectionState(nil, 0, nil, 0, 5)
	s2 := s.Toggle()
	if s == s2 {
		t.Error("expected new instance")
	}
	if len(s2.Selected) != 0 {
		t.Error("selected should still be empty")
	}
}

// TestMove verifies cursor movement with clamping and viewport auto-scroll.
func TestMove_Forward(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.Move(1)
	if s2.Cursor != 1 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestMove_ClampsAtLast(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.Move(100)
	if s2.Cursor != 2 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestMove_BackwardFromZeroClamps(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.Move(-1)
	if s2.Cursor != 0 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestMove_ReturnsNewInstance(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.Move(1)
	if s == s2 {
		t.Error("expected new instance")
	}
	if s.Cursor != 0 {
		t.Error("original should not be mutated")
	}
}

func TestMove_EmptyListStaysZero(t *testing.T) {
	s := NewSelectionState(nil, 0, nil, 0, 5)
	s2 := s.Move(1)
	if s2.Cursor != 0 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestMove_ViewportScrollsDownWhenCursorExitsBottom(t *testing.T) {
	s := NewSelectionState(makeRepos(10), 2, nil, 0, 3)
	s2 := s.Move(1)
	if s2.Cursor != 3 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
	if s2.ViewportStart <= 0 {
		t.Error("viewport should have scrolled down")
	}
}

func TestMove_ViewportScrollsUpWhenCursorExitsTop(t *testing.T) {
	s := NewSelectionState(makeRepos(10), 3, nil, 3, 3)
	s2 := s.Move(-1)
	if s2.Cursor != 2 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
	if s2.ViewportStart >= 3 {
		t.Error("viewport should have scrolled up")
	}
}

// TestSelectAllNone verifies select-all and select-none.
func TestSelectAll_SelectsEveryIndex(t *testing.T) {
	s := makeState(4, 5)
	s2 := s.SelectAll()
	if len(s2.Selected) != 4 {
		t.Errorf("selected len = %d", len(s2.Selected))
	}
	for i := 0; i < 4; i++ {
		if !s2.IsSelected(i) {
			t.Errorf("index %d not selected", i)
		}
	}
}

func TestSelectNone_ClearsSelection(t *testing.T) {
	s := NewSelectionState(makeRepos(4), 0, map[int]bool{0: true, 1: true, 2: true, 3: true}, 0, 5)
	s2 := s.SelectNone()
	if len(s2.Selected) != 0 {
		t.Errorf("selected len = %d", len(s2.Selected))
	}
}

func TestSelectAll_ReturnsNewInstance(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.SelectAll()
	if s == s2 {
		t.Error("expected new instance")
	}
	if len(s.Selected) != 0 {
		t.Error("original should not be mutated")
	}
}

func TestSelectNone_ReturnsNewInstance(t *testing.T) {
	s := NewSelectionState(makeRepos(3), 0, map[int]bool{0: true}, 0, 5)
	s2 := s.SelectNone()
	if s == s2 {
		t.Error("expected new instance")
	}
	if !s.IsSelected(0) {
		t.Error("original should not be mutated")
	}
}

func TestSelectAll_EmptyRepos(t *testing.T) {
	s := NewSelectionState(nil, 0, nil, 0, 5)
	s2 := s.SelectAll()
	if len(s2.Selected) != 0 {
		t.Error("selected should be empty")
	}
}

// TestVisibleSlice verifies the visible slice returns correct rows.
func TestVisibleSlice_CorrectLengthFullViewport(t *testing.T) {
	s := makeState(10, 3)
	slc := s.VisibleSlice()
	if len(slc) != 3 {
		t.Errorf("len = %d", len(slc))
	}
}

func TestVisibleSlice_LessWhenFewerRepos(t *testing.T) {
	s := makeState(2, 5)
	slc := s.VisibleSlice()
	if len(slc) != 2 {
		t.Errorf("len = %d", len(slc))
	}
}

func TestVisibleSlice_CursorItemMarked(t *testing.T) {
	s := makeState(5, 5)
	slc := s.VisibleSlice()
	if !slc[0].IsCursor {
		t.Error("expected first row to be cursor")
	}
	if slc[0].Repo.Name != "repo-0" {
		t.Errorf("repo name = %q", slc[0].Repo.Name)
	}
}

func TestVisibleSlice_NonCursorItemNotMarked(t *testing.T) {
	s := makeState(5, 5)
	slc := s.VisibleSlice()
	if slc[1].IsCursor {
		t.Error("expected second row to NOT be cursor")
	}
}

func TestVisibleSlice_SelectedItemMarked(t *testing.T) {
	s := NewSelectionState(makeRepos(5), 0, map[int]bool{2: true}, 0, 5)
	slc := s.VisibleSlice()
	if !slc[2].IsSelected {
		t.Error("expected row 2 to be selected")
	}
}

func TestVisibleSlice_UnselectedItemNotMarked(t *testing.T) {
	s := makeState(5, 5)
	slc := s.VisibleSlice()
	if slc[1].IsSelected {
		t.Error("expected row 1 to NOT be selected")
	}
}

func TestVisibleSlice_ViewportOffsetRespected(t *testing.T) {
	s := NewSelectionState(makeRepos(10), 5, nil, 5, 3)
	slc := s.VisibleSlice()
	if len(slc) != 3 {
		t.Errorf("len = %d", len(slc))
	}
	if slc[0].Repo.Name != "repo-5" {
		t.Errorf("repo name = %q", slc[0].Repo.Name)
	}
}

func TestVisibleSlice_EmptyRepos(t *testing.T) {
	s := NewSelectionState(nil, 0, nil, 0, 5)
	slc := s.VisibleSlice()
	if len(slc) != 0 {
		t.Errorf("len = %d", len(slc))
	}
}

// TestHandleKey verifies key dispatch.
func TestHandleKey_DownMovesCursor(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("down")
	if s2.Cursor != 1 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestHandleKey_UpMovesCursorBack(t *testing.T) {
	s := NewSelectionState(makeRepos(5), 2, nil, 0, 5)
	s2 := s.HandleKey("up")
	if s2.Cursor != 1 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestHandleKey_SpaceToggles(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("space")
	if !s2.IsSelected(0) {
		t.Error("expected cursor 0 to be selected")
	}
}

func TestHandleKey_ASelectsAll(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("a")
	if len(s2.Selected) != 5 {
		t.Errorf("selected len = %d", len(s2.Selected))
	}
}

func TestHandleKey_NSelectsNone(t *testing.T) {
	s := NewSelectionState(makeRepos(5), 0, map[int]bool{0: true, 1: true}, 0, 5)
	s2 := s.HandleKey("n")
	if len(s2.Selected) != 0 {
		t.Errorf("selected len = %d", len(s2.Selected))
	}
}

func TestHandleKey_UnknownKeyReturnsSameState(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("z")
	if s != s2 {
		t.Error("expected same instance for unknown key")
	}
}

// TestFilterAndJump verifies filter, jump, page, and hidden_selected_count.
func namedRepos(names []string) []Repo {
	repos := make([]Repo, len(names))
	for i, n := range names {
		repos[i] = Repo{
			Name:     n,
			SSHURL:   fmt.Sprintf("git@github.com:user/%s.git", n),
			PushedAt: "2026-01-01",
		}
	}
	return repos
}

func stateWith(names []string, cursor int, selected []int, vp int, h int, filter string) *SelectionState {
	sel := make(map[int]bool, len(selected))
	for _, i := range selected {
		sel[i] = true
	}
	repos := namedRepos(names)
	return NewSelectionState(repos, cursor, sel, vp, h).WithFilter(filter)
}

func TestFilterFieldDefaultEmpty(t *testing.T) {
	s := stateWith([]string{"a", "b"}, 0, nil, 0, 5, "")
	if s.Filter != "" {
		t.Errorf("filter = %q", s.Filter)
	}
}

func TestApplyFilter_ReturnsNewState(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "gamma"}, 0, nil, 0, 5, "")
	s2 := s.WithFilter("be")
	if s2.Filter != "be" {
		t.Errorf("filter = %q", s2.Filter)
	}
	if s.Filter != "" {
		t.Error("original should be unchanged")
	}
}

func TestVisibleIndices_NoFilter(t *testing.T) {
	s := stateWith([]string{"a", "b", "c"}, 0, nil, 0, 5, "")
	vis := s.VisibleIndices()
	if len(vis) != 3 {
		t.Errorf("len = %d", len(vis))
	}
}

func TestVisibleIndices_SubstringMatch(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "alphabet"}, 0, nil, 0, 5, "alpha")
	vis := s.VisibleIndices()
	if len(vis) != 2 || vis[0] != 0 || vis[1] != 2 {
		t.Errorf("visible = %v", vis)
	}
}

func TestVisibleIndices_CaseInsensitive(t *testing.T) {
	s := stateWith([]string{"Alpha", "Beta"}, 0, nil, 0, 5, "ALP")
	vis := s.VisibleIndices()
	if len(vis) != 1 || vis[0] != 0 {
		t.Errorf("visible = %v", vis)
	}
}

func TestFilterPreservesSelected(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "gamma"}, 0, []int{0, 2}, 0, 5, "alpha")
	if !s.IsSelected(0) || !s.IsSelected(2) {
		t.Error("selection should be preserved")
	}
}

func TestClearFilter(t *testing.T) {
	s := stateWith([]string{"alpha", "beta"}, 0, nil, 0, 5, "a")
	s2 := s.ClearFilter()
	if s2.Filter != "" {
		t.Errorf("filter = %q", s2.Filter)
	}
}

func TestCursorClampsToVisibleAfterFilter(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "gamma"}, 2, nil, 0, 5, "alpha")
	vis := s.VisibleIndices()
	found := false
	for _, i := range vis {
		if i == s.Cursor {
			found = true
			break
		}
	}
	if !found {
		t.Error("cursor should be in visible indices")
	}
}

func TestHiddenSelectedCount(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "gamma"}, 0, []int{0, 1, 2}, 0, 5, "alpha")
	if s.HiddenSelectedCount() != 2 {
		t.Errorf("hidden = %d", s.HiddenSelectedCount())
	}
}

func TestHiddenSelectedCountZeroWhenNoFilter(t *testing.T) {
	s := stateWith([]string{"a", "b"}, 0, []int{0, 1}, 0, 5, "")
	if s.HiddenSelectedCount() != 0 {
		t.Errorf("hidden = %d", s.HiddenSelectedCount())
	}
}

func TestJumpTop(t *testing.T) {
	s := NewSelectionState(namedRepos([]string{"a", "b", "c"}), 2, nil, 1, 5)
	s2 := s.JumpTop()
	if s2.Cursor != 0 || s2.ViewportStart != 0 {
		t.Errorf("cursor=%d vp=%d", s2.Cursor, s2.ViewportStart)
	}
}

func TestJumpBottom(t *testing.T) {
	s := NewSelectionState(namedRepos([]string{"a", "b", "c", "d", "e", "f"}), 0, nil, 0, 3)
	s2 := s.JumpBottom()
	if s2.Cursor != 5 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestJumpBottomWithFilter(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "alphabet"}, 0, nil, 0, 5, "alpha")
	s2 := s.JumpBottom()
	if s2.Cursor != 2 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestPageDown(t *testing.T) {
	names := make([]string, 20)
	for i := range names {
		names[i] = fmt.Sprintf("r%d", i)
	}
	s := NewSelectionState(namedRepos(names), 0, nil, 0, 5)
	s2 := s.PageDown()
	if s2.Cursor != 5 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestPageUpAtTop(t *testing.T) {
	names := make([]string, 20)
	for i := range names {
		names[i] = fmt.Sprintf("r%d", i)
	}
	s := NewSelectionState(namedRepos(names), 0, nil, 0, 5)
	s2 := s.PageUp()
	if s2.Cursor != 0 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestPageDownAtBottom(t *testing.T) {
	s := NewSelectionState(namedRepos([]string{"r0", "r1", "r2", "r3", "r4"}), 4, nil, 0, 5)
	s2 := s.PageDown()
	if s2.Cursor != 4 {
		t.Errorf("cursor = %d", s2.Cursor)
	}
}

func TestSelectAll_OperatesOnVisibleOnly(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "alphabet"}, 0, nil, 0, 5, "alpha")
	s2 := s.SelectAll()
	if len(s2.Selected) != 2 || !s2.IsSelected(0) || !s2.IsSelected(2) {
		t.Errorf("selected = %v", s2.Selected)
	}
}

func TestSelectNone_ClearsOnlyVisible(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "alphabet"}, 0, []int{0, 1, 2}, 0, 5, "alpha")
	s2 := s.SelectNone()
	if len(s2.Selected) != 1 || !s2.IsSelected(1) {
		t.Errorf("selected = %v (should only have index 1)", s2.Selected)
	}
}

// TestMoveStaysInVisibleAfterFilter regression tests.
func TestMoveDownStaysInVisibleAfterFilter(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "alphabet"}, 0, nil, 0, 5, "alpha")
	s2 := s.Move(1)
	if !s2.isVisible(s2.Cursor) {
		t.Error("cursor should be in visible indices")
	}
}

func TestMoveUpStaysInVisibleAfterFilter(t *testing.T) {
	s := stateWith([]string{"alpha", "beta", "alphabet"}, 1, nil, 0, 5, "alpha")
	s2 := s.Move(-1)
	if !s2.isVisible(s2.Cursor) {
		t.Error("cursor should be in visible indices")
	}
}

// TestImmutabilityInvariant verifies all mutating methods return new instances.
func TestImmutabilityInvariant_Toggle(t *testing.T) {
	s := makeState(3, 5)
	orig := len(s.Selected)
	s.Toggle()
	if len(s.Selected) != orig {
		t.Error("original should not be mutated")
	}
}

func TestImmutabilityInvariant_Move(t *testing.T) {
	s := makeState(3, 5)
	orig := s.Cursor
	s.Move(2)
	if s.Cursor != orig {
		t.Error("original should not be mutated")
	}
}

func TestImmutabilityInvariant_SelectAll(t *testing.T) {
	s := makeState(3, 5)
	s.SelectAll()
	if len(s.Selected) != 0 {
		t.Error("original should not be mutated")
	}
}

func TestImmutabilityInvariant_SelectNone(t *testing.T) {
	s := NewSelectionState(makeRepos(3), 0, map[int]bool{0: true, 1: true}, 0, 5)
	orig := len(s.Selected)
	s.SelectNone()
	if len(s.Selected) != orig {
		t.Error("original should not be mutated")
	}
}

func TestImmutabilityInvariant_HandleKey(t *testing.T) {
	s := makeState(5, 5)
	origCursor := s.Cursor
	origSel := len(s.Selected)
	s.HandleKey("down")
	s.HandleKey("space")
	if s.Cursor != origCursor {
		t.Error("original cursor should not be mutated")
	}
	if len(s.Selected) != origSel {
		t.Error("original selected should not be mutated")
	}
}

// TestToggleFilters verifies filter toggle keys.
func TestToggleSoloOnly(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.ToggleSoloOnly()
	if !s2.SoloOnly {
		t.Error("SoloOnly should be true")
	}
	s3 := s2.ToggleSoloOnly()
	if s3.SoloOnly {
		t.Error("SoloOnly should be false")
	}
}

func TestToggleExcludeForks(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.ToggleExcludeForks()
	if !s2.ExcludeForks {
		t.Error("ExcludeForks should be true")
	}
}

func TestToggleExcludeExistingReadme(t *testing.T) {
	s := makeState(3, 5)
	s2 := s.ToggleExcludeExistingReadme()
	if !s2.ExcludeExistingReadme {
		t.Error("ExcludeExistingReadme should be true")
	}
}

// TestHandleKeyS tests solo toggle.
func TestHandleKey_S_TogglesSoloOnly(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("s")
	if !s2.SoloOnly {
		t.Error("SoloOnly should be true after 's'")
	}
}

// TestHandleKeyF tests exclude forks toggle.
func TestHandleKey_F_TogglesExcludeForks(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("F")
	if !s2.ExcludeForks {
		t.Error("ExcludeForks should be true after 'F'")
	}
}

// TestHandleKeyR tests exclude existing readme toggle.
func TestHandleKey_R_TogglesExcludeExistingReadme(t *testing.T) {
	s := makeState(5, 5)
	s2 := s.HandleKey("r")
	if !s2.ExcludeExistingReadme {
		t.Error("ExcludeExistingReadme should be true after 'r'")
	}
}

// TestResizeViewport verifies viewport resize preserves state.
func TestResizeViewport(t *testing.T) {
	s := makeState(10, 5)
	s = s.WithFilter("re")
	s = s.ToggleSoloOnly()
	s2 := s.ResizeViewport(10)
	if s2.ViewportHeight != 10 {
		t.Errorf("ViewportHeight = %d", s2.ViewportHeight)
	}
	if s2.Filter != "re" {
		t.Errorf("Filter lost: %q", s2.Filter)
	}
	if !s2.SoloOnly {
		t.Error("SoloOnly lost")
	}
	if s.ViewportHeight != 5 {
		t.Error("original should not be mutated")
	}
}

// TestResizeViewportClampsMinimum verifies viewport minimum of 1.
func TestResizeViewportClampsMinimum(t *testing.T) {
	s := makeState(10, 5)
	s2 := s.ResizeViewport(0)
	if s2.ViewportHeight != 1 {
		t.Errorf("ViewportHeight = %d, want 1", s2.ViewportHeight)
	}
}
