// Package review invokes the `claude` subprocess + blast-radius / secret guards.
package review

import (
	"context"
	_ "embed"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/salamientark/writeme/internal/safety"
	"github.com/salamientark/writeme/internal/secrets"
)

//go:embed embedded/SKILL.md
var SkillMD string

// EnvAllowlist is the exact env-var set passed to claude.
var EnvAllowlist = map[string]bool{
	"PATH": true, "HOME": true, "USER": true, "LOGNAME": true,
	"SHELL": true, "LANG": true, "TERM": true, "TMPDIR": true,
}

// EnvPrefixes are the allowlisted env-var prefixes.
var EnvPrefixes = []string{"CLAUDE_", "LC_", "XDG_"}

// ScrubEnv returns the filtered env preserving only allowlisted keys.
// Extra is appended (overriding earlier values) for per-job sandbox vars.
func ScrubEnv(base []string, extra []string) []string {
	out := make([]string, 0, len(base))
	for _, kv := range base {
		k, _, ok := strings.Cut(kv, "=")
		if !ok {
			continue
		}
		if EnvAllowlist[k] {
			out = append(out, kv)
			continue
		}
		for _, p := range EnvPrefixes {
			if strings.HasPrefix(k, p) {
				out = append(out, kv)
				break
			}
		}
	}
	out = append(out, extra...)
	return out
}

// StageSkill writes the embedded SKILL.md into <repoDir>/.claude/skills/create-readme/.
// repoDir MUST resolve under basePath; otherwise an error is returned
// (defense-in-depth against path traversal — RT-H9).
// Returns an idempotent cleanup func.
func StageSkill(basePath, repoDir string) (func(), error) {
	cleanBase := filepath.Clean(basePath)
	cleanRepo := filepath.Clean(repoDir)
	rel, err := filepath.Rel(cleanBase, cleanRepo)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return func() {}, fmt.Errorf("repoDir %q not under base %q", repoDir, basePath)
	}
	dst := filepath.Join(cleanRepo, ".claude", "skills", "create-readme", "SKILL.md")
	var prev []byte
	hadPrev := false
	if b, err := os.ReadFile(dst); err == nil {
		hadPrev = true
		prev = b
	} else if !errors.Is(err, os.ErrNotExist) {
		return func() {}, err
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return func() {}, err
	}
	if err := os.WriteFile(dst, []byte(SkillMD), 0o644); err != nil {
		return func() {}, err
	}
	return func() {
		if hadPrev {
			_ = os.WriteFile(dst, prev, 0o644)
			return
		}
		_ = os.Remove(dst)
		// Drop only directories created by this call (Remove fails if non-empty).
		_ = os.Remove(filepath.Join(cleanRepo, ".claude", "skills", "create-readme"))
		_ = os.Remove(filepath.Join(cleanRepo, ".claude", "skills"))
		_ = os.Remove(filepath.Join(cleanRepo, ".claude"))
	}, nil
}

// Status enumerates the GenerationResult outcomes.
type Status string

const (
	StatusReady       Status = "ready"
	StatusTimeout     Status = "timeout"
	StatusNonzero     Status = "nonzero"
	StatusBlastRadius Status = "blast_radius"
	StatusFailed      Status = "failed"
)

// GenerationResult mirrors the Python GenerationResult.
type GenerationResult struct {
	Status        Status
	OldContent    string
	NewContent    string
	PrevDraft     string // last draft before this iteration's redo (empty on first pass)
	RiskyFiles    []string
	SecretMatches []string
	Error         string
}

// Runner invokes claude. Production = ShellRunner; tests inject fakes.
type Runner interface {
	Run(ctx context.Context, repoDir string, env []string) (exitCode int, stderr string, err error)
}

// ShellRunner exec's `claude -p /create-readme --permission-mode acceptEdits`.
type ShellRunner struct{}

// Run launches claude in its own process group so the entire tree can be
// killed on context cancellation.
func (ShellRunner) Run(ctx context.Context, repoDir string, env []string) (int, string, error) {
	cmd := exec.CommandContext(ctx, "claude", "-p", "/create-readme", "--permission-mode", "acceptEdits")
	cmd.Dir = repoDir
	cmd.Env = env
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	stdinNull, err := os.Open(os.DevNull)
	if err != nil {
		return -1, "", err
	}
	defer stdinNull.Close()
	cmd.Stdin = stdinNull
	var sb strings.Builder
	cmd.Stderr = &sb
	cmd.Cancel = func() error {
		if cmd.Process != nil {
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		}
		return nil
	}
	err = cmd.Run()
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return -1, sb.String(), context.DeadlineExceeded
	}
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode(), sb.String(), nil
		}
		return -1, sb.String(), err
	}
	return 0, sb.String(), nil
}

// GenerateDraft executes the full pipeline: risky scan → restore baseline →
// claude → blast-radius → secret scan.
func GenerateDraft(ctx context.Context, runner Runner, basePath, repoDir string, env []string) (GenerationResult, error) {
	risky, err := secrets.WalkRiskyFiles(repoDir)
	if err != nil {
		return GenerationResult{}, fmt.Errorf("walk risky files: %w", err)
	}
	restoreBaseline(ctx, repoDir)
	old := readFile(filepath.Join(repoDir, "README.md"))

	cleanup, err := StageSkill(basePath, repoDir)
	if err != nil {
		return GenerationResult{}, fmt.Errorf("stage skill: %w", err)
	}
	exitCode, stderr, runErr := runner.Run(ctx, repoDir, env)
	cleanup() // unstage BEFORE blast-radius so .claude/ doesn't trigger guard.
	if errors.Is(runErr, context.DeadlineExceeded) {
		return GenerationResult{Status: StatusTimeout, OldContent: old, RiskyFiles: risky, Error: stderr}, nil
	}
	if runErr != nil {
		return GenerationResult{Status: StatusFailed, OldContent: old, RiskyFiles: risky, Error: runErr.Error() + "\n" + stderr}, nil
	}
	if exitCode != 0 {
		return GenerationResult{Status: StatusNonzero, OldContent: old, RiskyFiles: risky, Error: fmt.Sprintf("exit=%d\n%s", exitCode, stderr)}, nil
	}
	touched, err := safety.BlastRadius(ctx, repoDir)
	if err != nil {
		return GenerationResult{}, fmt.Errorf("blast radius: %w", err)
	}
	if len(touched) > 0 {
		return GenerationResult{
			Status: StatusBlastRadius, OldContent: old, RiskyFiles: risky,
			Error: "claude_touched_other_files",
		}, nil
	}
	newContent := readFile(filepath.Join(repoDir, "README.md"))
	if old == newContent && newContent == "" {
		// Nothing produced.
		return GenerationResult{Status: StatusFailed, OldContent: old, RiskyFiles: risky, Error: "readme_not_generated"}, nil
	}
	matches := secrets.Scan(newContent)
	return GenerationResult{
		Status: StatusReady, OldContent: old, NewContent: newContent,
		RiskyFiles: risky, SecretMatches: matches,
	}, nil
}

func readFile(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	return string(b)
}

func restoreBaseline(ctx context.Context, dir string) {
	for _, args := range [][]string{
		{"git", "checkout", "--", "README.md"},
		{"git", "clean", "-f", "README.md"},
	} {
		cmd := exec.CommandContext(ctx, args[0], args[1:]...)
		cmd.Dir = dir
		_ = cmd.Run()
	}
}
