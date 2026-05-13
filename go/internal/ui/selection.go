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

func (m *selectionModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		h := msg.Height - 6
		if h < 5 {
			h = 5
		}
		m.state = m.state.ResizeViewport(h)
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
	case "esc":
		m.filterMode = false
		return m, nil
	case "enter":
		m.filterMode = false
		return m, nil
	case "backspace":
		if len(m.filterBuf) > 0 {
			m.filterBuf = m.filterBuf[:len(m.filterBuf)-1]
		}
		m.state = m.state.WithFilter(m.filterBuf)
		return m, nil
	default:
		s := msg.String()
		if len(s) == 1 && isPrintable(s) {
			m.filterBuf += s
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

// View renders the selection screen.
func (m *selectionModel) View() string {
	if m.width == 0 {
		return "loading..."
	}

	filterStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("6"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
	selectedStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("2"))
	cursorStyle := lipgloss.NewStyle().Reverse(true).Bold(true)
	headerStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("6"))

	state := m.state
	rows := state.VisibleSlice()

	var b strings.Builder

	fmt.Fprintf(&b, "%s (%d repos, %d selected)\n\n",
		headerStyle.Render("writeme — select repos"),
		len(state.Repos), len(state.Selected))

	for _, row := range rows {
		check := "[ ]"
		if row.IsSelected {
			check = selectedStyle.Render("[x]")
		}
		name := row.Repo.Name
		if len(name) > 40 {
			name = name[:37] + "..."
		}
		flags := ""
		if row.Repo.HadReadmeBefore {
			flags = dimStyle.Render(" README")
		}
		if row.Repo.IsFork {
			flags += dimStyle.Render(" FORK")
		}
		line := fmt.Sprintf("%s %-40s%s", check, name, flags)
		if row.IsCursor {
			line = cursorStyle.Render(line)
		}
		fmt.Fprintln(&b, line)
	}

	rendered := len(rows)
	if state.ViewportHeight > rendered {
		for i := 0; i < state.ViewportHeight-rendered; i++ {
			fmt.Fprintln(&b, dimStyle.Render(" ~"))
		}
	}
	fmt.Fprintln(&b)

	if m.filterMode {
		fmt.Fprintf(&b, "%s\n", filterStyle.Render("filter: "+m.filterBuf+"_"))
	} else {
		nSel := len(state.Selected)
		var toggles []string
		if state.SoloOnly {
			toggles = append(toggles, "solo")
		}
		if state.ExcludeForks {
			toggles = append(toggles, "no-forks")
		}
		if state.ExcludeExistingReadme {
			toggles = append(toggles, "no-readme")
		}
		togStr := ""
		if len(toggles) > 0 {
			togStr = "  [" + strings.Join(toggles, " · ") + "]"
		}
		hidden := state.HiddenSelectedCount()
		hiddenStr := ""
		if hidden > 0 {
			hiddenStr = fmt.Sprintf(" (%d hidden)", hidden)
		}

		footer := fmt.Sprintf(
			"arrows move · space toggle · / filter · s solo · F forks · r readme · "+
				"enter confirm · a all · n none · q quit    %d/%d selected%s%s",
			nSel, len(state.Repos), hiddenStr, togStr,
		)
		fmt.Fprint(&b, filterStyle.Render(footer))
	}

	return b.String()
}
