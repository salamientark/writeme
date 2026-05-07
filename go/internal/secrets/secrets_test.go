package secrets

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestScan(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want []string
	}{
		{"AWS key", "key=AKIAIOSFODNN7EXAMPLE", []string{"AKIAIOSFODNN7EXAMPLE"}},
		{"GitHub token", "token: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", []string{"ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}},
		{"OpenAI key", "sk-1234567890abcdefghij", []string{"sk-1234567890abcdefghij"}},
		{"PEM", "-----BEGIN RSA PRIVATE KEY-----\n...", []string{"-----BEGIN RSA PRIVATE KEY-----"}},
		{"generic api_key quoted", `api_key = "abcdefghijklmnopqrst"`, []string{`api_key = "abcdefghijklmnopqrst"`}},
		{"prose without assignment", "This token is interesting but not assigned.", nil},
		{"short value not a secret", `token: "abc"`, nil},
		{"clean text", "Hello world", nil},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := Scan(tc.in)
			if len(got) != len(tc.want) {
				t.Fatalf("got %v want %v", got, tc.want)
			}
			for i := range got {
				if !strings.Contains(got[i], tc.want[i]) && got[i] != tc.want[i] {
					t.Errorf("got %q want %q", got[i], tc.want[i])
				}
			}
		})
	}
}

func TestWalkRiskyFiles(t *testing.T) {
	root := t.TempDir()
	mk := func(rel string) {
		full := filepath.Join(root, rel)
		_ = os.MkdirAll(filepath.Dir(full), 0o755)
		_ = os.WriteFile(full, []byte("x"), 0o644)
	}
	mk(".env")
	mk(".env.local")
	mk("subdir/key.pem")
	mk("creds/server.key")
	mk("credentials.json")
	mk(".aws/credentials")
	mk(".ssh/id_rsa")
	mk("README.md") // should NOT match

	got, err := WalkRiskyFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	wants := []string{".env", ".env.local", "key.pem", "server.key", "credentials.json", "credentials", "id_rsa"}
	for _, w := range wants {
		found := false
		for _, p := range got {
			if filepath.Base(p) == w {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("missing %q in %v", w, got)
		}
	}
	for _, p := range got {
		if filepath.Base(p) == "README.md" {
			t.Errorf("README.md must not match: %v", p)
		}
	}
}
