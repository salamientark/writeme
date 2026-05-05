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


def read_key(rd) -> str:
    """Read a single key from *rd* (a /dev/tty bytes file). Returns symbolic name.

    Names: 'up','down','left','right','home','end','pgup','pgdn','delete',
    'enter','space','esc','backspace', or the literal character.
    Empty string on EOF.
    """
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
            return _decode(ch.decode("utf-8", "ignore"))
        b1 = rd.read(1)
        if not b1:
            return "esc"
        if b1 != b"[":
            return _decode("\x1b" + b1.decode("ascii", "ignore"))
        seq = b"\x1b["
        while True:
            b = rd.read(1)
            if not b:
                break
            seq += b
            if b.isalpha() or b == b"~":
                break
            if len(seq) > 8:
                break
        return _decode(seq.decode("ascii", "ignore"))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
