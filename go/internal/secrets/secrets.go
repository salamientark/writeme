// Package secrets scans text for secret patterns and walks repos for risky files.
package secrets

import (
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`AKIA[0-9A-Z]{16}`),
	regexp.MustCompile(`gh[pousr]_[A-Za-z0-9]{36,}`),
	regexp.MustCompile(`sk-[A-Za-z0-9\-]{20,}`),
	regexp.MustCompile(`-----BEGIN [A-Z ]*PRIVATE KEY-----`),
	regexp.MustCompile(`(?i)(?:api[_-]?key|secret|token)\s*[=:]\s*['"][A-Za-z0-9_\-]{16,}['"]`),
}

// Scan returns every secret-like substring found in s.
func Scan(s string) []string {
	var out []string
	for _, re := range secretPatterns {
		out = append(out, re.FindAllString(s, -1)...)
	}
	return out
}

// Risky file patterns. Directories use trailing "/**".
var riskyGlobs = []string{
	".env",
	".env.*",
	"*.pem",
	"*.key",
	"credentials.json",
	".aws/**",
	".ssh/**",
}

// WalkRiskyFiles returns sorted paths matching the risky-glob set.
func WalkRiskyFiles(repoDir string) ([]string, error) {
	found := map[string]bool{}
	err := filepath.WalkDir(repoDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			if os.IsPermission(err) {
				return nil
			}
			return err
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(repoDir, path)
		if err != nil {
			return nil
		}
		base := filepath.Base(rel)
		for _, pattern := range riskyGlobs {
			if strings.HasSuffix(pattern, "/**") {
				dirName := strings.TrimSuffix(pattern, "/**")
				parts := strings.Split(filepath.ToSlash(rel), "/")
				for _, p := range parts[:len(parts)-1] {
					if p == dirName {
						found[path] = true
						break
					}
				}
				continue
			}
			if ok, _ := filepath.Match(pattern, base); ok {
				found[path] = true
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(found))
	for p := range found {
		out = append(out, p)
	}
	sort.Strings(out)
	return out, nil
}
