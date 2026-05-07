package filters

import (
	"reflect"
	"testing"
)

func TestParseSelection(t *testing.T) {
	const N = 10
	tests := []struct {
		in       string
		wantKind ParseKind
		want     []int
	}{
		{"1", ParseOK, []int{0}},
		{"1,3,5", ParseOK, []int{0, 2, 4}},
		{"5-7", ParseOK, []int{4, 5, 6}},
		{"1,3,5-7", ParseOK, []int{0, 2, 4, 5, 6}},
		{"  1 , 3 , 5-7 ", ParseOK, []int{0, 2, 4, 5, 6}},
		{"1-10", ParseOK, []int{0, 1, 2, 3, 4, 5, 6, 7, 8, 9}},
		{"a", ParseAll, nil},
		{"A", ParseAll, nil},
		{"q", ParseQuit, nil},
		{"Q", ParseQuit, nil},
		{"", ParseQuit, nil},
		{"   ", ParseQuit, nil},
		{"foo", ParseError, nil},
		{"99", ParseError, nil},
		{"0", ParseError, nil},
		{"-1", ParseError, nil},
		{"7-5", ParseError, nil},
		{"1,foo,3", ParseError, nil},
		{"1,,3", ParseError, nil},
		{"1-2-3", ParseError, nil},
	}
	for _, tc := range tests {
		t.Run(tc.in, func(t *testing.T) {
			got := ParseSelection(tc.in, N)
			if got.Kind != tc.wantKind {
				t.Fatalf("kind=%v want %v (msg=%s)", got.Kind, tc.wantKind, got.Message)
			}
			if tc.wantKind == ParseOK && !reflect.DeepEqual(got.Indices, tc.want) {
				t.Errorf("got %v want %v", got.Indices, tc.want)
			}
		})
	}
}

func TestApplyAndPredicates(t *testing.T) {
	repos := []Repo{
		{Name: "a", IsFork: false, HadReadmeBefore: false, Contributors: []string{"u1"}, HasContributors: true},
		{Name: "b", IsFork: true, HadReadmeBefore: true, Contributors: []string{"u1", "u2"}, HasContributors: true},
		{Name: "c", IsFork: false, HadReadmeBefore: true, Contributors: []string{}, HasContributors: true},
		{Name: "d", IsFork: false, HadReadmeBefore: false, HasContributors: false},
	}
	// solo-only: a (1 contrib) + c (0 contrib). d has no contrib data → excluded.
	got := Apply(repos, true, false, false)
	names := []string{}
	for _, r := range got {
		names = append(names, r.Name)
	}
	if !reflect.DeepEqual(names, []string{"a", "c"}) {
		t.Errorf("solo-only got %v", names)
	}
	// exclude forks
	got = Apply(repos, false, true, false)
	names = nil
	for _, r := range got {
		names = append(names, r.Name)
	}
	if !reflect.DeepEqual(names, []string{"a", "c", "d"}) {
		t.Errorf("exclude-forks got %v", names)
	}
	// exclude existing readme
	got = Apply(repos, false, false, true)
	names = nil
	for _, r := range got {
		names = append(names, r.Name)
	}
	if !reflect.DeepEqual(names, []string{"a", "d"}) {
		t.Errorf("exclude-readme got %v", names)
	}
	// All toggles → only a (solo, not fork, no readme)
	got = Apply(repos, true, true, true)
	names = nil
	for _, r := range got {
		names = append(names, r.Name)
	}
	if !reflect.DeepEqual(names, []string{"a"}) {
		t.Errorf("all toggles got %v", names)
	}
}
