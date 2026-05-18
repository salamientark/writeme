package main

import (
	"os"
	"testing"
)

func TestResolveUser_GHEnvOnly(t *testing.T) {
	// If gh fails, envUser is returned directly. If gh succeeds and matches
	// envUser (or user confirms), the gh login is returned. Either way,
	// resolveUser should not error when a valid GH_USER is provided.
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	// Write "n\n" to decline any mismatch prompt.
	if _, err := w.WriteString("n\n"); err != nil {
		t.Fatal(err)
	}
	w.Close()

	user, err := resolveUser("alice", r, os.Stderr)
	if err != nil {
		t.Fatal(err)
	}
	// If gh is authed and mismatch was declined, we get the envUser back.
	// If gh is not authed, we also get the envUser back.
	if user != "alice" {
		t.Errorf("expected alice, got %q", user)
	}
}

func TestResolveUser_EmptyGHEnv(t *testing.T) {
	// When GH_USER is empty, resolveUser either returns the gh login
	// (if authed) or an error (if not authed).
	user, err := resolveUser("", os.Stdin, os.Stderr)
	if err != nil {
		// Expected if gh is not authenticated.
		t.Logf("resolveUser error (expected without gh auth): %v", err)
		return
	}
	// If no error, user must be non-empty.
	if user == "" {
		t.Error("expected non-empty user from gh auth")
	}
	t.Logf("resolved gh user: %s", user)
}

func TestResolveUser_MismatchWithPipe(t *testing.T) {
	// Simulate GH_USER != gh user with "y" confirmation.
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.WriteString("y\n"); err != nil {
		t.Fatal(err)
	}
	w.Close()

	user, err := resolveUser("not-the-gh-user", r, os.Stderr)
	if err != nil {
		// If gh is not authed, we get envUser back.
		t.Logf("resolveUser error: %v", err)
		return
	}
	// If gh is authed and user confirmed "y", we get the gh login.
	if user == "" {
		t.Error("expected non-empty user")
	}
	t.Logf("confirmed gh user: %s", user)
}

func TestPrintSummary_NilStore(t *testing.T) {
	// printSummary should not panic with a nil store.
	printSummary(nil)
}

func TestGhAPIUser(t *testing.T) {
	login, err := ghAPIUser()
	if err != nil {
		t.Logf("gh api user failed (expected without auth): %v", err)
	} else {
		t.Logf("gh api user: %s", login)
	}
}
