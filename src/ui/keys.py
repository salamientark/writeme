"""Raw-key reader for interactive Rich screens (selection, menus, scroll).

Reads single keys from /dev/tty, mapping ANSI escape sequences to symbolic
names so callers can branch on `'up' / 'down' / 'pgup'` etc.
"""
from __future__ import annotations


def open_tty_rd():
    """Return a raw-bytes file for /dev/tty or None if unavailable."""
    try:
        return open("/dev/tty", "rb", buffering=0)
    except OSError:
        return None


_CSI_NAMES = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1b[H": "home",
    "\x1b[F": "end",
    "\x1b[5~": "pgup",
    "\x1b[6~": "pgdn",
    "\x1b[3~": "delete",
}


def _decode(seq: str) -> str:
    if seq in _CSI_NAMES:
        return _CSI_NAMES[seq]
    if seq == "\r" or seq == "\n":
        return "enter"
    if seq == " ":
        return "space"
    if seq == "\x1b":
        return "esc"
    if seq == "\x7f" or seq == "\b":
        return "backspace"
    return seq


_ESC_TIMEOUT = 0.05
_RAW_SEQ_CAP = 32


def read_key_raw(rd) -> str:
    """Read a single key, returning the raw sequence (no symbolic decoding).

    Returns the raw escape sequence (e.g. ``"\\x1b[A"``, ``"\\x1b[<0;12;5M"``)
    or single character for non-escape keys. Empty string on EOF.
    Callers needing symbolic names should use :func:`read_key`; callers needing
    raw bytes (e.g. SGR mouse parsing) should use this.
    """
    import select
    import termios
    import tty
    fd = rd.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = rd.read(1)
        if not ch:
            return ""
        if ch != b"\x1b":
            return ch.decode("utf-8", "ignore")
        # Disambiguate standalone Esc from start of escape sequence.
        ready, _, _ = select.select([fd], [], [], _ESC_TIMEOUT)
        if not ready:
            return "\x1b"
        b1 = rd.read(1)
        if not b1:
            return "\x1b"
        if b1 != b"[":
            return "\x1b" + b1.decode("ascii", "ignore")
        seq = b"\x1b["
        while True:
            b = rd.read(1)
            if not b:
                break
            seq += b
            # CSI terminators: any letter (incl. mouse 'M'/'m') or '~'.
            if b.isalpha() or b == b"~":
                break
            if len(seq) > _RAW_SEQ_CAP:
                break
        return seq.decode("ascii", "ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key(rd) -> str:
    """Read a single key from *rd* and return its symbolic name.

    Names: 'up','down','left','right','home','end','pgup','pgdn','delete',
    'enter','space','esc','backspace', or the literal character.
    Empty string on EOF.
    """
    raw = read_key_raw(rd)
    if raw == "":
        return ""
    return _decode(raw)
