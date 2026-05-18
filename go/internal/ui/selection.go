package ui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/salamientark/writeme/internal/selection"
)

// SelectionResult holds the outcome of the selection screen.
type SelectionResult struct {
	Repos []selection.Repo
	Quit  bool
}

// selectionModel is the bubbletea Model for repo selection.
type selectionModel struct {
	state      *selection.SelectionState
	filterMode bool
	filterBuf  string
	showHelp   bool
	width      int
	height     int
}

// RunSelection runs the interactive repo selection TUI.
// Returns the selected repos (empty if user quit/Ctrl+C).
func RunSelection(repos []selection.Repo) SelectionResult {
	m := &selectionModel{
		state: selection.NewSelectionState(repos, 0, nil, 0, 15),
	}
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
	final, err := p.Run()
	if err != nil {
		return SelectionResult{Quit: true}
	}
	fm := final.(*selectionModel)
	if fm.filterMode {
		return SelectionResult{Quit: true}
	}
	sel := fm.state
	var picked []selection.Repo
	for i := range sel.Repos {
		if sel.IsSelected(i) {
			picked = append(picked, sel.Repos[i])
		}
	}
	if len(picked) == 0 {
		return SelectionResult{Quit: true}
	}
	return SelectionResult{Repos: picked}
}

func (m *selectionModel) Init() tea.Cmd { return nil }

// viewportFor returns the list height that keeps the whole render within the
// terminal. Normal mode reserves 6 lines of chrome; filter mode and the help
// panel each show ~6 extra lines below the list, so reserve more.
func viewportFor(termHeight int, filtering, showHelp bool) int {
	reserve := 6
	min := 5
	if filtering || showHelp {
		reserve = 12
		min = 3
	}
	h := termHeight - reserve
	if h < min {
		h = min
	}
	return h
}

func (m *selectionModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.state = m.state.ResizeViewport(viewportFor(msg.Height, m.filterMode, m.showHelp)).Move(0)
		return m, nil

	case tea.KeyMsg:
		if m.filterMode {
			return m.handleFilterKey(msg)
		}
		return m.handleNormalKey(msg)
	}
	return m, nil
}

func (m *selectionModel) handleFilterKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		return m, tea.Quit
	case "esc", "enter":
		m.filterMode = false
		m.state = m.state.ResizeViewport(viewportFor(m.height, false, false)).Move(0)
		return m, nil
	case "backspace":
		if r := []rune(m.filterBuf); len(r) > 0 {
			m.filterBuf = string(r[:len(r)-1])
		}
		m.state = m.state.WithFilter(m.filterBuf)
		return m, nil
	default:
		// Accept a single printable rune (multibyte-safe).
		if r := msg.Runes; len(r) == 1 && r[0] >= 32 {
			m.filterBuf += string(r)
			m.state = m.state.WithFilter(m.filterBuf)
		}
		return m, nil
	}
}

func (m *selectionModel) handleNormalKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "q", "ctrl+c":
		return m, tea.Quit
	case "enter":
		return m, tea.Quit
	case "/":
		m.filterMode = true
		m.filterBuf = m.state.Filter
		m.state = m.state.ResizeViewport(viewportFor(m.height, true, false)).Move(0)
		return m, nil
	case "?":
		m.showHelp = !m.showHelp
		m.state = m.state.ResizeViewport(viewportFor(m.height, false, m.showHelp)).Move(0)
		return m, nil
	case "up", "k":
		m.state = m.state.Move(-1)
	case "down", "j":
		m.state = m.state.Move(1)
	case " ":
		m.state = m.state.Toggle()
	case "a":
		m.state = m.state.SelectAll()
	case "n":
		m.state = m.state.SelectNone()
	case "g":
		m.state = m.state.JumpTop()
	case "G":
		m.state = m.state.JumpBottom()
	case "pgup":
		m.state = m.state.PageUp()
	case "pgdown":
		m.state = m.state.PageDown()
	case "s":
		m.state = m.state.ToggleSoloOnly()
	case "F":
		m.state = m.state.ToggleExcludeForks()
	case "r":
		m.state = m.state.ToggleExcludeExistingReadme()
	}
	return m, nil
}

func isPrintable(s string) bool {
	if len(s) == 0 {
		return false
	}
	r := rune(s[0])
	return r >= 32 && r < 127
}

// Theme.
var (
	selAccent  = lipgloss.NewStyle().Foreground(lipgloss.Color("6"))
	selGreen   = lipgloss.NewStyle().Foreground(lipgloss.Color("2"))
	selDim     = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	selBadge   = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))
	selBracket = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	selName    = lipgloss.NewStyle().Foreground(lipgloss.Color("15"))
	selBorder  = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	selKey     = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
)

// truncWidth shortens s to at most w display columns (double-width runes and
// emoji counted correctly), appending "…" when it cuts.
func truncWidth(s string, w int) string {
	if w <= 0 {
		return ""
	}
	if lipgloss.Width(s) <= w {
		return s
	}
	var b strings.Builder
	for _, r := range s {
		if lipgloss.Width(b.String()+string(r)+"…") > w {
			break
		}
		b.WriteRune(r)
	}
	return b.String() + "…"
}

// padTo right-pads s (ANSI-aware) to width w.
func padTo(s string, w int) string {
	gap := w - lipgloss.Width(s)
	if gap <= 0 {
		return s
	}
	return s + strings.Repeat(" ", gap)
}

// titledBox wraps body lines in a rounded border with a title on the top
// seam and a right-aligned tag (e.g. count). innerW is the content width.
func titledBox(title, tag string, body []string, innerW int) string {
	bd := lipgloss.RoundedBorder()
	hbar := func(n int) string {
		if n < 0 {
			n = 0
		}
		return strings.Repeat(bd.Top, n)
	}
	// Clamp title+tag to the available width (innerW minus 2 lead dashes and
	// the 4 surrounding pad spaces) so a long title can't make fill negative
	// and blow the top border past the body/bottom width. Tag keeps priority.
	budget := innerW - 6
	if budget < 0 {
		budget = 0
	}
	if w := lipgloss.Width(tag); w > budget {
		tag = truncWidth(tag, budget)
		budget = 0
	} else {
		budget -= w
	}
	title = truncWidth(title, budget)
	titleSeg := ""
	if title != "" {
		titleSeg = " " + selAccent.Render(title) + " "
	}
	tagSeg := ""
	if tag != "" {
		tagSeg = " " + selDim.Render(tag) + " "
	}
	used := lipgloss.Width(titleSeg) + lipgloss.Width(tagSeg) + 2 // 2 lead dashes
	fill := innerW - used
	top := selBorder.Render(bd.TopLeft+hbar(1)) + titleSeg +
		selBorder.Render(hbar(fill)) + tagSeg + selBorder.Render(hbar(1)+bd.TopRight)
	bot := selBorder.Render(bd.BottomLeft + hbar(innerW) + bd.BottomRight)
	v := selBorder.Render(bd.Left)
	vr := selBorder.Render(bd.Right)

	var b strings.Builder
	b.WriteString(top + "\n")
	clip := lipgloss.NewStyle().MaxWidth(innerW)
	for _, ln := range body {
		b.WriteString(v + padTo(clip.Render(ln), innerW) + vr + "\n")
	}
	b.WriteString(bot)
	return b.String()
}

// View renders the selection screen.
func (m *selectionModel) View() string {
	if m.width == 0 {
		return "loading..."
	}

	state := m.state
	innerW := m.width - 4 // 2 border + 1 lead/trail pad each side
	if innerW < 24 {
		innerW = 24
	}

	visTotal := len(state.VisibleIndices())
	rows := state.VisibleSlice()

	// --- list body ---
	body := make([]string, 0, state.ViewportHeight+1)
	for _, row := range rows {
		cur := " "
		if row.IsCursor {
			cur = selAccent.Render("›")
		}
		check := selDim.Render("○")
		if row.IsSelected {
			check = selGreen.Render("◉")
		}
		// Fixed-width tag zone so chips stack in a vertical column:
		// readme slot = len("[readme]")=8, fork slot = len("[fork]")=6.
		readmeSlot := strings.Repeat(" ", 8)
		if row.Repo.HadReadmeBefore {
			readmeSlot = selBracket.Render("[") + selBadge.Render("readme") + selBracket.Render("]")
		}
		forkSlot := strings.Repeat(" ", 6)
		if row.Repo.IsFork {
			forkSlot = selBracket.Render("[") + selDim.Render("fork") + selBracket.Render("]")
		}
		right := readmeSlot + " " + forkSlot // constant visual width 15
		// 1 pad + cursor + 1 + check + 2 spaces = 6 cols before name.
		nameMax := innerW - 6 - lipgloss.Width(right) - 1
		if nameMax < 4 {
			nameMax = 4
		}
		name := truncWidth(row.Repo.Name, nameMax)
		nst := selName
		if !row.IsSelected {
			nst = selDim
		}
		left := fmt.Sprintf(" %s %s  %s", cur, check, nst.Render(name))
		gap := innerW - lipgloss.Width(left) - lipgloss.Width(right) - 1
		if gap < 1 {
			gap = 1
		}
		body = append(body, left+strings.Repeat(" ", gap)+right+" ")
	}
	for len(body) < state.ViewportHeight {
		body = append(body, "")
	}

	// --- in-box footer: filter chips + scroll position ---
	var chips []string
	if state.SoloOnly {
		chips = append(chips, "solo")
	}
	if state.ExcludeForks {
		chips = append(chips, "no-forks")
	}
	if state.ExcludeExistingReadme {
		chips = append(chips, "no-readme")
	}
	leftFoot := ""
	if len(chips) > 0 {
		leftFoot = selDim.Render(" filters: " + strings.Join(chips, " · "))
	}
	if hidden := state.HiddenSelectedCount(); hidden > 0 {
		leftFoot += selDim.Render(fmt.Sprintf("  (%d hidden selected)", hidden))
	}
	first, last := 0, 0
	if visTotal > 0 {
		first = state.ViewportStart + 1
		last = state.ViewportStart + len(rows)
	}
	up, down := selDim.Render("▲"), selDim.Render("▼")
	if state.ViewportStart == 0 {
		up = " "
	}
	if last >= visTotal {
		down = " "
	}
	pos := fmt.Sprintf("%s %d–%d / %d %s", up, first, last, visTotal, down)
	gap := innerW - lipgloss.Width(leftFoot) - lipgloss.Width(pos) - 1
	if gap < 1 {
		gap = 1
	}
	body = append(body, "") // blank separator row
	body = append(body, leftFoot+strings.Repeat(" ", gap)+selDim.Render(pos)+" ")

	tag := fmt.Sprintf("%d/%d selected", len(state.Selected), len(state.Repos))
	box := titledBox("writeme · select repositories", tag, body, innerW)

	var b strings.Builder
	b.WriteString(box)
	b.WriteString("\n")

	// --- help / filter input below the box ---
	switch {
	case m.filterMode:
		matches := fmt.Sprintf("%d matches", visTotal)
		input := " " + selAccent.Render("›") + " " + m.filterBuf +
			selAccent.Render("▏")
		fgap := innerW - lipgloss.Width(input) - lipgloss.Width(matches) - 1
		if fgap < 1 {
			fgap = 1
		}
		hint := selDim.Render("live filter  ·  ") +
			selKey.Render("enter") + selDim.Render("/") + selKey.Render("esc") +
			selDim.Render(" back to list to toggle/confirm")
		fbody := []string{
			input + strings.Repeat(" ", fgap) + selDim.Render(matches) + " ",
			"",
			" " + hint,
		}
		b.WriteString("\n")
		b.WriteString(titledBox("Filter", "", fbody, innerW))
	case m.showHelp:
		k := func(s string) string { return selKey.Render(s) }
		lines := []string{
			"  " + k("↑/↓ j/k") + "  move      " + k("g/G") + "  top / bottom",
			"  " + k("space") + "    toggle    " + k("a/n") + "  all / none",
			"  " + k("/") + "        filter    " + k("pgup/pgdn") + "  page",
			"  " + k("s") + "        solo      " + k("F") + "  forks   " + k("r") + "  readme",
			"  " + k("enter") + "    confirm   " + k("q") + "  quit    " + k("?") + "  close help",
		}
		b.WriteString("\n")
		b.WriteString(strings.Join(lines, "\n"))
	default:
		hint := "  " + selKey.Render("↑↓") + " navigate  " +
			selKey.Render("space") + " select  " +
			selKey.Render("/") + " filter  " +
			selKey.Render("enter") + " confirm  " +
			selKey.Render("?") + " help  " +
			selKey.Render("q") + " quit"
		b.WriteString(selDim.Render(hint))
	}

	return b.String()
}
