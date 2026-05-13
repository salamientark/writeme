package keys

import (
	"strings"
	"testing"
)

func TestDecode_EscapeSequences(t *testing.T) {
	tests := []struct {
		raw  string
		want string
	}{
		{"\x1b[A", "up"},
		{"\x1b[B", "down"},
		{"\x1b[C", "right"},
		{"\x1b[D", "left"},
		{"\x1b[H", "home"},
		{"\x1b[F", "end"},
		{"\x1b[5~", "pgup"},
		{"\x1b[6~", "pgdn"},
		{"\x1b[3~", "delete"},
	}
	for _, tt := range tests {
		got := decode(tt.raw)
		if got != tt.want {
			t.Errorf("decode(%q) = %q, want %q", tt.raw, got, tt.want)
		}
	}
}

func TestDecode_EnterVariants(t *testing.T) {
	if decode("\r") != "enter" {
		t.Errorf("decode(\\r) = %q", decode("\r"))
	}
	if decode("\n") != "enter" {
		t.Errorf("decode(\\n) = %q", decode("\n"))
	}
}

func TestDecode_SpecialChars(t *testing.T) {
	if decode(" ") != "space" {
		t.Errorf("decode(space) = %q", decode(" "))
	}
	if decode("\x1b") != "esc" {
		t.Errorf("decode(esc) = %q", decode("\x1b"))
	}
	if decode("\x7f") != "backspace" {
		t.Errorf("decode(\\x7f) = %q", decode("\x7f"))
	}
	if decode("\b") != "backspace" {
		t.Errorf("decode(\\b) = %q", decode("\b"))
	}
}

func TestDecode_LiteralChar(t *testing.T) {
	got := decode("x")
	if got != "x" {
		t.Errorf("decode(x) = %q", got)
	}
}

func TestDecode_EmptyString(t *testing.T) {
	if decode("") != "" {
		t.Errorf("decode(\"\") = %q", decode(""))
	}
}

// TestDecodeMapExhaustive verifies every entry in csiNames round-trips correctly.
func TestDecodeMapExhaustive(t *testing.T) {
	for seq, name := range csiNames {
		got := decode(seq)
		if got != name {
			t.Errorf("decode(%q) = %q, want %q", seq, got, name)
		}
	}
}

// TestDecodeMapUniqueness verifies no duplicate names.
func TestDecodeMapUniqueness(t *testing.T) {
	seen := map[string]string{}
	for seq, name := range csiNames {
		if other, ok := seen[name]; ok {
			t.Errorf("duplicate name %q for seq %q and %q", name, other, seq)
		}
		seen[name] = seq
	}
}

// TestReadKeyRaw_EOF returns empty string.
func TestReadKeyRaw_EOF(t *testing.T) {
	rd := strings.NewReader("")
	got := ReadKeyRaw(rd)
	if got != "" {
		t.Errorf("got %q, want empty string", got)
	}
}

// TestReadKeyRaw_SingleChar returns the character.
func TestReadKeyRaw_SingleChar(t *testing.T) {
	rd := strings.NewReader("a")
	got := ReadKeyRaw(rd)
	if got != "a" {
		t.Errorf("got %q, want a", got)
	}
}

// TestReadKeyRaw_EscNoFollow returns Esc.
func TestReadKeyRaw_EscNoFollow(t *testing.T) {
	rd := strings.NewReader("\x1b")
	got := ReadKeyRaw(rd)
	if got != "\x1b" {
		t.Errorf("got %q, want esc", got)
	}
}

// TestReadKeyRaw_CSIUp returns full sequence.
func TestReadKeyRaw_CSIUp(t *testing.T) {
	rd := strings.NewReader("\x1b[A")
	got := ReadKeyRaw(rd)
	if got != "\x1b[A" {
		t.Errorf("got %q, want up arrow sequence", got)
	}
}

// TestReadKeyRaw_CSILong returns full sequence up to terminator.
func TestReadKeyRaw_CSILong(t *testing.T) {
	rd := strings.NewReader("\x1b[1;5A")
	got := ReadKeyRaw(rd)
	if got != "\x1b[1;5A" {
		t.Errorf("got %q", got)
	}
}

// TestReadKey caches symbolic resolution.
func TestReadKey_EscapeSequence(t *testing.T) {
	rd := strings.NewReader("\x1b[A")
	got := ReadKey(rd)
	if got != "up" {
		t.Errorf("got %q, want up", got)
	}
}

func TestReadKey_SingleChar(t *testing.T) {
	rd := strings.NewReader("x")
	got := ReadKey(rd)
	if got != "x" {
		t.Errorf("got %q, want x", got)
	}
}

func TestReadKey_EOF(t *testing.T) {
	rd := strings.NewReader("")
	got := ReadKey(rd)
	if got != "" {
		t.Errorf("got %q, want empty", got)
	}
}
