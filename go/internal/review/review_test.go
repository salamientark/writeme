package review

import (
	"strings"
	"testing"
)

func TestSkillMDEmbedded(t *testing.T) {
	if !strings.Contains(SkillMD, "name: create-readme") {
		t.Fatalf("embedded SKILL.md missing expected frontmatter; got %q", SkillMD[:min(100, len(SkillMD))])
	}
}
