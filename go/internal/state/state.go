// Package state implements the JSONL state store and resume prompt.
package state

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	StatusPushed     = "pushed"
	StatusPROpened   = "pr_opened"
	StatusCommitOnly = "commit_only"
	StatusSkipped    = "skipped"
	StatusFailed     = "failed"
)

var processedStatuses = map[string]bool{
	StatusPushed: true, StatusPROpened: true, StatusCommitOnly: true,
}

// IsProcessed reports whether status counts as processed.
func IsProcessed(status string) bool { return processedStatuses[status] }

var ghUserCharRe = regexp.MustCompile(`^[A-Za-z0-9-]+$`)

// ValidateGHUser returns an error if name is not a valid GitHub username.
// Rules: 1-39 alphanumeric/hyphen chars; no leading/trailing hyphen; no consecutive hyphens.
func ValidateGHUser(name string) error {
	if name == "" || len(name) > 39 || !ghUserCharRe.MatchString(name) {
		return fmt.Errorf("invalid GitHub username: %q", name)
	}
	if name[0] == '-' || name[len(name)-1] == '-' || strings.Contains(name, "--") {
		return fmt.Errorf("invalid GitHub username: %q", name)
	}
	return nil
}

// Clock provides the current time.
type Clock interface{ Now() time.Time }

type realClock struct{}

func (realClock) Now() time.Time { return time.Now().UTC() }

// RealClock returns the production clock (UTC time.Now()).
func RealClock() Clock { return realClock{} }

// FixedClock returns a Clock that always reports ts.
func FixedClock(ts time.Time) Clock { return fixedClock{ts: ts} }

type fixedClock struct{ ts time.Time }

func (f fixedClock) Now() time.Time { return f.ts }

// Record is one entry in the JSONL state file.
type Record struct {
	Repo   string `json:"repo"`
	Status string `json:"status"`
	TS     string `json:"ts"`
	Mode   string `json:"mode,omitempty"`
	Error  string `json:"error,omitempty"`
	PRURL  string `json:"pr_url,omitempty"`
}

// RecordOpts holds optional fields.
type RecordOpts struct {
	Mode  string
	Error string
	PRURL string
}

// Summary aggregates state file content.
type Summary struct {
	Counts      map[string]int
	PRURLs      []string
	FailedRepos []string
}

// Store is an append-only JSONL state file.
type Store struct {
	user     string
	stateDir string
	file     string
	clock    Clock
	mu       sync.Mutex
}

// New constructs a Store. State directory is NOT created until first write.
func New(user, stateDir string, clock Clock) (*Store, error) {
	if err := ValidateGHUser(user); err != nil {
		return nil, err
	}
	if clock == nil {
		clock = RealClock()
	}
	return &Store{
		user:     user,
		stateDir: stateDir,
		file:     filepath.Join(stateDir, "state-"+user+".jsonl"),
		clock:    clock,
	}, nil
}

// File returns the absolute state-file path.
func (s *Store) File() string { return s.file }

// HasPriorState reports whether the state file exists.
func (s *Store) HasPriorState() bool {
	_, err := os.Stat(s.file)
	return err == nil
}

// Record appends one record.
func (s *Store) Record(repo, status string, opts RecordOpts) error {
	rec := Record{
		Repo:   repo,
		Status: status,
		TS:     s.clock.Now().UTC().Format("2006-01-02T15:04:05-07:00"),
		Mode:   opts.Mode,
		Error:  opts.Error,
		PRURL:  opts.PRURL,
	}
	data, err := json.Marshal(rec)
	if err != nil {
		return fmt.Errorf("marshal record: %w", err)
	}
	if err := os.MkdirAll(s.stateDir, 0o755); err != nil {
		return fmt.Errorf("mkdir state dir: %w", err)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := os.OpenFile(s.file, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return fmt.Errorf("open state file: %w", err)
	}
	defer f.Close()
	if _, err := f.Write(append(data, '\n')); err != nil {
		return fmt.Errorf("write state: %w", err)
	}
	return nil
}

func (s *Store) readAll() ([]Record, error) {
	f, err := os.Open(s.file)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, fmt.Errorf("open state file: %w", err)
	}
	defer f.Close()
	var out []Record
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var r Record
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			continue
		}
		out = append(out, r)
	}
	return out, sc.Err()
}

// LoadProcessed returns last-record-wins map of processed repos.
func (s *Store) LoadProcessed() (map[string]Record, error) {
	recs, err := s.readAll()
	if err != nil {
		return nil, err
	}
	last := map[string]Record{}
	for _, r := range recs {
		last[r.Repo] = r
	}
	out := map[string]Record{}
	for repo, r := range last {
		if IsProcessed(r.Status) {
			out[repo] = r
		}
	}
	return out, nil
}

// Summary aggregates counts plus PR URLs and failed repos.
func (s *Store) Summary() (Summary, error) {
	recs, err := s.readAll()
	if err != nil {
		return Summary{}, err
	}
	sum := Summary{Counts: map[string]int{}}
	for _, r := range recs {
		sum.Counts[r.Status]++
		if r.Status == StatusPROpened && r.PRURL != "" {
			sum.PRURLs = append(sum.PRURLs, r.PRURL)
		}
		if r.Status == StatusFailed {
			sum.FailedRepos = append(sum.FailedRepos, r.Repo)
		}
	}
	return sum, nil
}

// ResumeChoice from PromptResume.
type ResumeChoice string

const (
	ResumeKeep  ResumeChoice = "resume"
	ResumeAll   ResumeChoice = "all"
	ResumeFresh ResumeChoice = "fresh"
	ResumeQuit  ResumeChoice = "quit"
)

// PromptResume reads from stdin until a valid choice (r/a/s/q).
func PromptResume(stdin io.Reader, stdout io.Writer, processedCount int) (ResumeChoice, error) {
	r := bufio.NewReader(stdin)
	for {
		fmt.Fprintf(stdout, "Found %d repos already processed. [r]esume (skip processed) / [a]ll incl. failed / [s]tart fresh / [q]uit: ", processedCount)
		line, err := r.ReadString('\n')
		if err != nil && line == "" {
			return "", fmt.Errorf("read stdin: %w", err)
		}
		switch strings.ToLower(strings.TrimSpace(line)) {
		case "r":
			return ResumeKeep, nil
		case "a":
			return ResumeAll, nil
		case "s":
			return ResumeFresh, nil
		case "q":
			return ResumeQuit, nil
		}
	}
}
