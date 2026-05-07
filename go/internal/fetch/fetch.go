// Package fetch lists GitHub repos via gh GraphQL.
package fetch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"sort"
	"time"

	"github.com/salamientark/writeme/internal/safety"
)

const (
	HardLimit = 1000
	PageSize  = 100
)

// Repo is the typed result for one repo.
type Repo struct {
	Name            string
	SSHURL          string
	PushedAt        string
	HadReadmeBefore bool
	DiskUsage       int
	IsFork          bool
}

// Fetcher lists owned repos for a user.
type Fetcher interface {
	ListRepos(ctx context.Context, user string, limit int) ([]Repo, error)
}

// GraphQLQuery is the canonical query used in production. Exported for fakes.
const GraphQLQuery = `query FetchRepos($login: String!, $first: Int!, $after: String) {
  user(login: $login) {
    repositories(first: $first, after: $after, ownerAffiliations: OWNER, isArchived: false, orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name sshUrl pushedAt diskUsage isFork
        readmeMd: object(expression: "HEAD:README.md") { ... on Blob { text } }
        readmeLc: object(expression: "HEAD:readme.md") { ... on Blob { text } }
        readmeCap: object(expression: "HEAD:Readme.md") { ... on Blob { text } }
        readmeRst: object(expression: "HEAD:README.rst") { ... on Blob { text } }
        readmeDocs: object(expression: "HEAD:docs/README.md") { ... on Blob { text } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
  rateLimit { remaining resetAt }
}`

// rawNode mirrors the JSON shape gh returns.
type rawNode struct {
	Name       string           `json:"name"`
	SSHURL     string           `json:"sshUrl"`
	PushedAt   string           `json:"pushedAt"`
	DiskUsage  int              `json:"diskUsage"`
	IsFork     bool             `json:"isFork"`
	ReadmeMd   *json.RawMessage `json:"readmeMd"`
	ReadmeLc   *json.RawMessage `json:"readmeLc"`
	ReadmeCap  *json.RawMessage `json:"readmeCap"`
	ReadmeRst  *json.RawMessage `json:"readmeRst"`
	ReadmeDocs *json.RawMessage `json:"readmeDocs"`
}

type rawPage struct {
	Errors []struct {
		Message string `json:"message"`
	} `json:"errors"`
	Data struct {
		User struct {
			Repositories struct {
				Nodes    []rawNode `json:"nodes"`
				PageInfo struct {
					HasNextPage bool   `json:"hasNextPage"`
					EndCursor   string `json:"endCursor"`
				} `json:"pageInfo"`
			} `json:"repositories"`
		} `json:"user"`
		RateLimit struct {
			Remaining int    `json:"remaining"`
			ResetAt   string `json:"resetAt"`
		} `json:"rateLimit"`
	} `json:"data"`
}

// PageRunner executes one paged gh-api call. Production = Shell (exec), tests = fake.
type PageRunner func(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error)

// GHFetcher implements Fetcher via the gh CLI.
type GHFetcher struct {
	Run    PageRunner
	Stderr io.Writer
}

// NewGHFetcher returns a Fetcher with default shell runner.
func NewGHFetcher(stderr io.Writer) *GHFetcher {
	return &GHFetcher{Run: shellRun, Stderr: stderr}
}

func shellRun(ctx context.Context, user string, pageSize int, cursor string) ([]byte, error) {
	args := []string{
		"api", "graphql",
		"-f", "query=" + GraphQLQuery,
		"-F", "login=" + user,
		"-F", fmt.Sprintf("first=%d", pageSize),
	}
	if cursor != "" {
		args = append(args, "-F", "after="+cursor)
	}
	cmd := exec.CommandContext(ctx, "gh", args...)
	return cmd.Output()
}

// ListRepos paginates until limit is reached or no more pages.
func (f *GHFetcher) ListRepos(ctx context.Context, user string, limit int) ([]Repo, error) {
	if limit > HardLimit {
		fmt.Fprintf(f.Stderr, "Warning: limit %d exceeds maximum; capped at %d.\n", limit, HardLimit)
		limit = HardLimit
	}
	var (
		all    []Repo
		cursor string
	)
	for len(all) < limit {
		need := limit - len(all)
		size := PageSize
		if need < size {
			size = need
		}
		out, err := f.Run(ctx, user, size, cursor)
		if err != nil {
			return nil, fmt.Errorf("gh graphql page: %w", err)
		}
		var page rawPage
		if err := json.Unmarshal(out, &page); err != nil {
			return nil, fmt.Errorf("decode gh graphql: %w", err)
		}
		if len(page.Errors) > 0 {
			return nil, fmt.Errorf("gh graphql errors: %s", page.Errors[0].Message)
		}
		for _, n := range page.Data.User.Repositories.Nodes {
			r, err := decodeNode(n)
			if err != nil {
				return nil, err
			}
			all = append(all, r)
		}
		// Rate-limit handling — sleep if remaining < 10.
		if page.Data.RateLimit.Remaining > 0 && page.Data.RateLimit.Remaining < 10 {
			wait := timeUntil(page.Data.RateLimit.ResetAt)
			fmt.Fprintf(f.Stderr, "Rate limit low (remaining=%d). Sleeping %.1fs until reset.\n",
				page.Data.RateLimit.Remaining, wait.Seconds())
			select {
			case <-time.After(wait):
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
		if !page.Data.User.Repositories.PageInfo.HasNextPage {
			break
		}
		cursor = page.Data.User.Repositories.PageInfo.EndCursor
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].PushedAt > all[j].PushedAt })
	return all, nil
}

// readmePresent reports whether a GraphQL readme field is a non-null object.
// *json.RawMessage stays non-nil when the JSON value is literal `null`, so a
// pointer check alone is insufficient.
func readmePresent(raw *json.RawMessage) bool {
	if raw == nil {
		return false
	}
	b := bytes.TrimSpace(*raw)
	return len(b) > 0 && string(b) != "null"
}

func decodeNode(n rawNode) (Repo, error) {
	if err := safety.ValidateRepoName(n.Name); err != nil {
		return Repo{}, err
	}
	if err := safety.ValidateSSHURL(n.SSHURL); err != nil {
		return Repo{}, err
	}
	hasReadme := readmePresent(n.ReadmeMd) || readmePresent(n.ReadmeLc) ||
		readmePresent(n.ReadmeCap) || readmePresent(n.ReadmeRst) ||
		readmePresent(n.ReadmeDocs)
	return Repo{
		Name:            n.Name,
		SSHURL:          n.SSHURL,
		PushedAt:        n.PushedAt,
		DiskUsage:       n.DiskUsage,
		IsFork:          n.IsFork,
		HadReadmeBefore: hasReadme,
	}, nil
}

func timeUntil(iso string) time.Duration {
	if iso == "" {
		return 0
	}
	t, err := time.Parse(time.RFC3339, iso)
	if err != nil {
		return 0
	}
	d := time.Until(t)
	if d < 0 {
		return 0
	}
	return d
}
