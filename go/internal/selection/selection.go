// Package selection: render-free plain-mode repo selection prompt + immutable SelectionState.
package selection

import (
	"bufio"
	"fmt"
	"io"
	"strings"

	"github.com/salamientark/writeme/internal/fetch"
	"github.com/salamientark/writeme/internal/filters"
)

// RenderPlain writes a numbered list of repos.
func RenderPlain(w io.Writer, repos []fetch.Repo) {
	for i, r := range repos {
		fmt.Fprintf(w, "%4d  %s\n", i+1, r.Name)
	}
}

// Prompt reads a selection line from stdin until input parses successfully
// or returns Quit. Returns 0-indexed positions into repos (or all/empty).
func Prompt(stdin io.Reader, stdout io.Writer, total int) ([]int, error) {
	r, ok := stdin.(*bufio.Reader)
	if !ok {
		r = bufio.NewReader(stdin)
	}
	for {
		fmt.Fprintf(stdout, "Select repos (e.g. 1,3-5,8 or 'all'): ")
		line, err := r.ReadString('\n')
		if err != nil && line == "" {
			return nil, fmt.Errorf("read stdin: %w", err)
		}
		res := filters.ParseSelection(line, total)
		switch res.Kind {
		case filters.ParseQuit:
			return nil, nil
		case filters.ParseAll:
			out := make([]int, total)
			for i := range out {
				out[i] = i
			}
			return out, nil
		case filters.ParseOK:
			return res.Indices, nil
		case filters.ParseError:
			fmt.Fprintf(stdout, "  %s\n", res.Message)
		}
	}
}

// Repo is an immutable representation of a GitHub repository for the selection TUI.
type Repo struct {
	Name            string
	SSHURL          string
	PushedAt        string
	HadReadmeBefore bool
	DiskUsage       int
	IsFork          bool
	Contributors    []string
}

// VisibleRow is a single rendered row: (repo, is_selected, is_cursor).
type VisibleRow struct {
	Repo       Repo
	IsSelected bool
	IsCursor   bool
}

// SelectionState is an immutable TUI selection state: cursor position, selected set, viewport.
// All methods that logically "change" state return a new SelectionState pointer.
type SelectionState struct {
	Repos                 []Repo
	Cursor                int
	Selected              map[int]bool
	ViewportStart         int
	ViewportHeight        int
	Filter                string
	SoloOnly              bool
	ExcludeForks          bool
	ExcludeExistingReadme bool
}

// NewSelectionState creates a new SelectionState.
func NewSelectionState(repos []Repo, cursor int, selected map[int]bool, viewportStart int, viewportHeight int) *SelectionState {
	if selected == nil {
		selected = make(map[int]bool)
	}
	return &SelectionState{
		Repos:          repos,
		Cursor:         cursor,
		Selected:       selected,
		ViewportStart:  viewportStart,
		ViewportHeight: viewportHeight,
	}
}

// copy returns a shallow copy of the state with a new Selected map.
func (s *SelectionState) copy() *SelectionState {
	sel := make(map[int]bool, len(s.Selected))
	for k, v := range s.Selected {
		sel[k] = v
	}
	return &SelectionState{
		Repos:                 s.Repos,
		Cursor:                s.Cursor,
		Selected:              sel,
		ViewportStart:         s.ViewportStart,
		ViewportHeight:        s.ViewportHeight,
		Filter:                s.Filter,
		SoloOnly:              s.SoloOnly,
		ExcludeForks:          s.ExcludeForks,
		ExcludeExistingReadme: s.ExcludeExistingReadme,
	}
}

// IsSelected reports whether a repo index is in the selected set.
func (s *SelectionState) IsSelected(idx int) bool {
	return s.Selected[idx]
}

// Toggle flips the selection state of the repo at the current cursor position.
func (s *SelectionState) Toggle() *SelectionState {
	if len(s.Repos) == 0 {
		return s.copy()
	}
	s2 := s.copy()
	if s2.Selected[s2.Cursor] {
		delete(s2.Selected, s2.Cursor)
	} else {
		s2.Selected[s2.Cursor] = true
	}
	return s2
}

// Move adjusts the cursor by delta rows, clamping to visible range and auto-scrolling viewport.
func (s *SelectionState) Move(delta int) *SelectionState {
	if len(s.Repos) == 0 {
		return s.copy()
	}
	visible := s.VisibleIndices()
	if len(visible) == 0 {
		return s.copy()
	}
	curVP := indexOf(visible, s.Cursor)
	if curVP < 0 {
		curVP = 0
	}
	newVP := curVP + delta
	if newVP < 0 {
		newVP = 0
	}
	if newVP >= len(visible) {
		newVP = len(visible) - 1
	}
	newCursor := visible[newVP]
	newVPStart := s.ViewportStart

	if newVP >= newVPStart+s.ViewportHeight {
		newVPStart = newVP - s.ViewportHeight + 1
	}
	if newVP < newVPStart {
		newVPStart = newVP
	}
	maxStart := len(visible) - s.ViewportHeight
	if maxStart < 0 {
		maxStart = 0
	}
	if newVPStart > maxStart {
		newVPStart = maxStart
	}
	if newVPStart < 0 {
		newVPStart = 0
	}

	s2 := s.copy()
	s2.Cursor = newCursor
	s2.ViewportStart = newVPStart
	return s2
}

// SelectAll marks every visible repo as selected.
func (s *SelectionState) SelectAll() *SelectionState {
	s2 := s.copy()
	for _, i := range s.VisibleIndices() {
		s2.Selected[i] = true
	}
	return s2
}

// SelectNone clears selections of visible repos (preserves out-of-filter selections).
func (s *SelectionState) SelectNone() *SelectionState {
	s2 := s.copy()
	for _, i := range s.VisibleIndices() {
		delete(s2.Selected, i)
	}
	return s2
}

// WithFilter returns a new state with the filter applied, clamping cursor to visible range.
func (s *SelectionState) WithFilter(q string) *SelectionState {
	s2 := s.copy()
	s2.Filter = q
	s2.ViewportStart = 0
	visible := s2.VisibleIndices()
	if len(visible) == 0 {
		return s2
	}
	cursor := s2.Cursor
	if !s2.isVisible(cursor) {
		cursor = visible[0]
	}
	return s2.reapplyFiltersCursor(cursor)
}

// ClearFilter removes the active filter.
func (s *SelectionState) ClearFilter() *SelectionState {
	return s.WithFilter("")
}

// JumpTop moves cursor to first visible row.
func (s *SelectionState) JumpTop() *SelectionState {
	visible := s.VisibleIndices()
	if len(visible) == 0 {
		return s
	}
	s2 := s.copy()
	s2.Cursor = visible[0]
	s2.ViewportStart = 0
	return s2
}

// JumpBottom moves cursor to last visible row.
func (s *SelectionState) JumpBottom() *SelectionState {
	visible := s.VisibleIndices()
	if len(visible) == 0 {
		return s
	}
	maxStart := len(visible) - s.ViewportHeight
	if maxStart < 0 {
		maxStart = 0
	}
	s2 := s.copy()
	s2.Cursor = visible[len(visible)-1]
	s2.ViewportStart = maxStart
	return s2
}

// PageDown moves cursor down by viewport height.
func (s *SelectionState) PageDown() *SelectionState {
	return s.Move(s.ViewportHeight)
}

// PageUp moves cursor up by viewport height.
func (s *SelectionState) PageUp() *SelectionState {
	return s.Move(-s.ViewportHeight)
}

// ToggleSoloOnly toggles the solo-only filter.
func (s *SelectionState) ToggleSoloOnly() *SelectionState {
	s2 := s.copy()
	s2.SoloOnly = !s2.SoloOnly
	return s2.reapplyFilters()
}

// ToggleExcludeForks toggles the exclude-forks filter.
func (s *SelectionState) ToggleExcludeForks() *SelectionState {
	s2 := s.copy()
	s2.ExcludeForks = !s2.ExcludeForks
	return s2.reapplyFilters()
}

// ToggleExcludeExistingReadme toggles the exclude-existing-readme filter.
func (s *SelectionState) ToggleExcludeExistingReadme() *SelectionState {
	s2 := s.copy()
	s2.ExcludeExistingReadme = !s2.ExcludeExistingReadme
	return s2.reapplyFilters()
}

// reapplyFilters clamps cursor + viewport after a filter-state change (F8 cursor-keep).
func (s *SelectionState) reapplyFilters() *SelectionState {
	visible := s.VisibleIndices()
	if len(visible) == 0 {
		s2 := s.copy()
		s2.ViewportStart = 0
		return s2
	}
	cursor := s.Cursor
	if !s.isVisible(cursor) {
		cursor = visible[0]
	}
	return s.reapplyFiltersCursor(cursor)
}

// reapplyFiltersCursor clamps viewport around the given cursor.
func (s *SelectionState) reapplyFiltersCursor(cursor int) *SelectionState {
	visible := s.VisibleIndices()
	curVP := indexOf(visible, cursor)
	if curVP < 0 {
		curVP = 0
	}
	vpStart := 0
	if curVP >= s.ViewportHeight {
		vpStart = curVP - s.ViewportHeight + 1
	}
	maxStart := len(visible) - s.ViewportHeight
	if maxStart < 0 {
		maxStart = 0
	}
	if vpStart > maxStart {
		vpStart = maxStart
	}
	if vpStart < 0 {
		vpStart = 0
	}
	s2 := s.copy()
	s2.Cursor = cursor
	s2.ViewportStart = vpStart
	return s2
}

// isVisible reports whether idx matches the current filter.
func (s *SelectionState) isVisible(idx int) bool {
	for _, v := range s.VisibleIndices() {
		if v == idx {
			return true
		}
	}
	return false
}

// VisibleIndices returns indices into Repos matching the current filter (case-insensitive)
// composed with predicate-toggle filters.
func (s *SelectionState) VisibleIndices() []int {
	q := strings.ToLower(s.Filter)
	var result []int
	for i, r := range s.Repos {
		if q != "" && !strings.Contains(strings.ToLower(r.Name), q) {
			continue
		}
		if s.SoloOnly && !filters.IsSolo(filtersRepo(r)) {
			continue
		}
		if s.ExcludeForks && r.IsFork {
			continue
		}
		if s.ExcludeExistingReadme && r.HadReadmeBefore {
			continue
		}
		result = append(result, i)
	}
	return result
}

// HiddenSelectedCount returns the count of selected repos not in current visible_indices.
func (s *SelectionState) HiddenSelectedCount() int {
	visible := make(map[int]bool, len(s.VisibleIndices()))
	for _, i := range s.VisibleIndices() {
		visible[i] = true
	}
	count := 0
	for i := range s.Selected {
		if !visible[i] {
			count++
		}
	}
	return count
}

// VisibleSlice returns the rows that should be rendered in the current viewport.
func (s *SelectionState) VisibleSlice() []VisibleRow {
	visible := s.VisibleIndices()
	start := s.ViewportStart
	if start > len(visible) {
		start = len(visible)
	}
	end := start + s.ViewportHeight
	if end > len(visible) {
		end = len(visible)
	}
	result := make([]VisibleRow, 0, end-start)
	for _, i := range visible[start:end] {
		result = append(result, VisibleRow{
			Repo:       s.Repos[i],
			IsSelected: s.Selected[i],
			IsCursor:   i == s.Cursor,
		})
	}
	return result
}

// HandleKey dispatches a key name to the appropriate state transition.
// Recognized keys: "up", "down", "space", "a", "n", "s", "F", "r".
// Unknown keys: returns self unchanged.
func (s *SelectionState) HandleKey(key string) *SelectionState {
	switch key {
	case "down":
		return s.Move(1)
	case "up":
		return s.Move(-1)
	case "space":
		return s.Toggle()
	case "a":
		return s.SelectAll()
	case "n":
		return s.SelectNone()
	case "s":
		return s.ToggleSoloOnly()
	case "F":
		return s.ToggleExcludeForks()
	case "r":
		return s.ToggleExcludeExistingReadme()
	default:
		return s
	}
}

// filtersRepo converts a selection.Repo to a filters.Repo for predicate checks.
func filtersRepo(r Repo) filters.Repo {
	return filters.Repo{
		Name:            r.Name,
		SSHURL:          r.SSHURL,
		PushedAt:        r.PushedAt,
		HadReadmeBefore: r.HadReadmeBefore,
		DiskUsage:       r.DiskUsage,
		IsFork:          r.IsFork,
		Contributors:    r.Contributors,
		HasContributors: len(r.Contributors) > 0,
	}
}

// indexOf returns the position of needle in haystack, or -1.
func indexOf(haystack []int, needle int) int {
	for i, v := range haystack {
		if v == needle {
			return i
		}
	}
	return -1
}

// ResizeViewport returns a new state with only the viewport size changed.
func (s *SelectionState) ResizeViewport(h int) *SelectionState {
	if h < 1 {
		h = 1
	}
	s2 := s.copy()
	s2.ViewportHeight = h
	return s2
}
