package ui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/salamientark/writeme/internal/diff"
)

// ReviewContext holds the data needed for the review screen.
type ReviewContext struct {
	RepoName     string
	Index        int
	Total        int
	HeadReadme   *string // nil means no prior README
	PrevDraft    *string // nil means first draft
	CurrentDraft string
}

// ReviewDecision is the user's choice from the review screen.
type ReviewDecision string

const (
	ReviewAccept  ReviewDecision = "accept"
	ReviewRedo    ReviewDecision = "redo"
	ReviewDiscard ReviewDecision = "discard"
	ReviewQuit    ReviewDecision = "quit"
)

// reviewModel is the bubbletea Model for the review screen.
type reviewModel struct {
	ctx       ReviewContext
	viewIdx   int
	offsets   []int // per-view scroll offset
	width     int
	height    int
}

var reviewViews = []string{"README", "diff_head", "diff_prev", "raw"}

var reviewViewLabels = map[string]string{
	"README":    "README",
	"diff_head": "diff vs HEAD",
	"diff_prev": "diff vs prev draft",
	"raw":       "raw markdown",
}

// RunReview runs the interactive review TUI. Returns the user's decision.
func RunReview(ctx ReviewContext) ReviewDecision {
	m := &reviewModel{
		ctx:     ctx,
		offsets: make([]int, len(reviewViews)),
	}
	p := tea.NewProgram(m, tea.WithAltScreen())
	final, err := p.Run()
	if err != nil {
		return ReviewQuit
	}
	fm := final.(*reviewModel)
	return fm.Result()
}

func (m *reviewModel) Init() tea.Cmd { return nil }

func (m *reviewModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case tea.KeyMsg:
		view := reviewViews[m.viewIdx]
		vp := m.viewport()
		total := m.lineCount(view)

		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "a":
			m.viewIdx = -1 // sentinel for accept
			return m, tea.Quit
		case "r":
			m.viewIdx = -2 // sentinel for redo
			return m, tea.Quit
		case "d":
			m.viewIdx = -3 // sentinel for discard
			return m, tea.Quit

		case "tab":
			m.viewIdx = (m.viewIdx + 1) % len(reviewViews)
		case "1":
			m.viewIdx = 1 // diff_head
		case "2":
			m.viewIdx = 2 // diff_prev
		case "v":
			m.viewIdx = 3 // raw

		case "j", "down":
			maxOff := total - vp
			if maxOff < 0 {
				maxOff = 0
			}
			if m.offsets[m.viewIdx] < maxOff {
				m.offsets[m.viewIdx]++
			}
		case "k", "up":
			if m.offsets[m.viewIdx] > 0 {
				m.offsets[m.viewIdx]--
			}
		case "pgdown", " ":
			maxOff := total - vp
			if maxOff < 0 {
				maxOff = 0
			}
			m.offsets[m.viewIdx] += vp
			if m.offsets[m.viewIdx] > maxOff {
				m.offsets[m.viewIdx] = maxOff
			}
		case "pgup", "b":
			m.offsets[m.viewIdx] -= vp
			if m.offsets[m.viewIdx] < 0 {
				m.offsets[m.viewIdx] = 0
			}
		case "g":
			m.offsets[m.viewIdx] = 0
		case "G":
			maxOff := total - vp
			if maxOff < 0 {
				maxOff = 0
			}
			m.offsets[m.viewIdx] = maxOff
		}
		return m, nil

	case tea.MouseMsg:
		if msg.Button == tea.MouseButtonWheelUp {
			if m.offsets[m.viewIdx] > 0 {
				m.offsets[m.viewIdx] -= 3
				if m.offsets[m.viewIdx] < 0 {
					m.offsets[m.viewIdx] = 0
				}
			}
		} else if msg.Button == tea.MouseButtonWheelDown {
			vp := m.viewport()
			total := m.lineCount(reviewViews[m.viewIdx])
			maxOff := total - vp
			if maxOff < 0 {
				maxOff = 0
			}
			m.offsets[m.viewIdx] += 3
			if m.offsets[m.viewIdx] > maxOff {
				m.offsets[m.viewIdx] = maxOff
			}
		}
		return m, nil
	}
	return m, nil
}

func (m *reviewModel) viewport() int {
	h := m.height - 4
	if h < 3 {
		h = 3
	}
	return h
}

func (m *reviewModel) lineCount(view string) int {
	content := m.renderView(view)
	return strings.Count(content, "\n") + 1
}

func (m *reviewModel) renderView(view string) string {
	switch view {
	case "README":
		return m.ctx.CurrentDraft
	case "diff_head":
		return diff.DiffVsHead(m.ctx.HeadReadme, m.ctx.CurrentDraft)
	case "diff_prev":
		return diff.DiffVsPrev(m.ctx.PrevDraft, m.ctx.CurrentDraft)
	case "raw":
		return m.ctx.CurrentDraft
	default:
		return ""
	}
}

// View renders the review screen.
func (m *reviewModel) View() string {
	if m.width == 0 || m.height == 0 {
		return "loading..."
	}

	view := reviewViews[m.viewIdx]
	content := m.renderView(view)

	headerStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("6"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
	bodyStyle := lipgloss.NewStyle().Width(m.width - 4)

	vp := m.viewport()
	allLines := strings.Split(content, "\n")
	total := len(allLines)
	offset := m.offsets[m.viewIdx]
	maxOff := total - vp
	if maxOff < 0 {
		maxOff = 0
	}
	if offset > maxOff {
		offset = maxOff
		m.offsets[m.viewIdx] = offset
	}
	end := offset + vp
	if end > total {
		end = total
	}
	window := allLines[offset:end]

	var b strings.Builder

	// Title.
	title := fmt.Sprintf("[%d/%d] %s", m.ctx.Index, m.ctx.Total, m.ctx.RepoName)
	fmt.Fprintf(&b, "%s\n", headerStyle.Render(title))

	// Body.
	for _, line := range window {
		fmt.Fprintln(&b, bodyStyle.Render(line))
	}

	// Fill remaining viewport space.
	for i := len(window); i < vp; i++ {
		fmt.Fprintln(&b, dimStyle.Render("~"))
	}

	// Footer.
	viewLabel := reviewViewLabels[view]
	scrollPos := fmt.Sprintf("lines %d-%d/%d", offset+1, end, total)
	if total == 0 {
		scrollPos = "empty"
	}
	footer := fmt.Sprintf(
		"a accept · r redo · d discard · q quit  |  %s  ·  %s  ·  tab cycle  ·  j/k scroll  ·  PgUp/PgDn  ·  g/G top/bot  ·  1 diff/HEAD  ·  2 diff/prev  ·  v raw",
		viewLabel, scrollPos,
	)
	fmt.Fprint(&b, dimStyle.Render(footer))

	return b.String()
}

// Result returns the final decision from the review model.
func (m *reviewModel) Result() ReviewDecision {
	switch m.viewIdx {
	case -1:
		return ReviewAccept
	case -2:
		return ReviewRedo
	case -3:
		return ReviewDiscard
	default:
		return ReviewQuit
	}
}
