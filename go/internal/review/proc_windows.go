//go:build windows

package review

import "os/exec"

// setProcessGroup is a no-op on Windows; process-group semantics differ and
// CommandContext already kills the direct child.
func setProcessGroup(cmd *exec.Cmd) {}

// killProcessGroup kills the child process.
func killProcessGroup(cmd *exec.Cmd) {
	_ = cmd.Process.Kill()
}
