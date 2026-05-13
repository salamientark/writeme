// Package keys decodes raw terminal key sequences into symbolic names.
// Used by the selection TUI and plain-mode key reading.
//
// When a bubbletea TUI is active, key reading is delegated to bubbletea.
// This package provides the CSI decode table shared across TUI modes and
// a plain-mode ReadKey fallback that works with any io.Reader.
package keys

import (
	"io"
)

// CSI escape sequence → symbolic name mapping.
var csiNames = map[string]string{
	"\x1b[A":  "up",
	"\x1b[B":  "down",
	"\x1b[C":  "right",
	"\x1b[D":  "left",
	"\x1b[H":  "home",
	"\x1b[F":  "end",
	"\x1b[5~": "pgup",
	"\x1b[6~": "pgdn",
	"\x1b[3~": "delete",
}

// decode converts a raw sequence to its symbolic name.
// Returns the literal string for unrecognized sequences.
func decode(seq string) string {
	if name, ok := csiNames[seq]; ok {
		return name
	}
	switch seq {
	case "\r", "\n":
		return "enter"
	case " ":
		return "space"
	case "\x1b":
		return "esc"
	case "\x7f", "\b":
		return "backspace"
	default:
		return seq
	}
}

// ReadKeyRaw reads a single raw key sequence from rd.
// For simple io.Reader (non-TTY, or pipes): reads one byte, or attempts
// to read a CSI sequence if the first byte is Esc. Returns "" on EOF.
//
// When connected to a real TTY, the caller should use bubbletea's key
// reading or set the terminal to raw mode before calling this function.
func ReadKeyRaw(rd io.Reader) string {
	var buf [1]byte
	n, err := rd.Read(buf[:])
	if err != nil || n == 0 {
		return ""
	}
	ch := buf[0]
	if ch != 0x1b { // Esc
		return string(ch)
	}
	// Try to read CSI follow bytes.
	seq := []byte{0x1b}
	buf2 := make([]byte, 1)
	n2, err := rd.Read(buf2[:])
	if err != nil || n2 == 0 {
		return "\x1b"
	}
	if buf2[0] != '[' {
		seq = append(seq, buf2[0])
		return string(seq)
	}
	seq = append(seq, '[')
	for {
		n3, err := rd.Read(buf2[:])
		if err != nil || n3 == 0 {
			break
		}
		seq = append(seq, buf2[0])
		// CSI terminators: any letter or '~'.
		if (buf2[0] >= 'A' && buf2[0] <= 'Z') || (buf2[0] >= 'a' && buf2[0] <= 'z') || buf2[0] == '~' {
			break
		}
		if len(seq) > 32 {
			break
		}
	}
	return string(seq)
}

// ReadKey reads a single key from rd and returns its symbolic name.
// See ReadKeyRaw for raw-mode requirements on real terminals.
func ReadKey(rd io.Reader) string {
	raw := ReadKeyRaw(rd)
	if raw == "" {
		return ""
	}
	return decode(raw)
}
