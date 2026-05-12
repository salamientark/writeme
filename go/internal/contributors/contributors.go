// Package contributors fetches contributor lists with bot strip + on-disk cache.
package contributors

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sync"
)

var botRe = regexp.MustCompile(`(?i)(.*\[bot\]$|^dependabot(-preview)?$|^github-actions$)`)

// IsBot reports whether login matches the bot heuristic.
func IsBot(login string) bool { return botRe.MatchString(login) }

// StripBots returns logins minus any bot identities.
func StripBots(logins []string) []string {
	out := make([]string, 0, len(logins))
	for _, l := range logins {
		if !IsBot(l) {
			out = append(out, l)
		}
	}
	return out
}

// CacheKey returns "name@pushed_at" used by the on-disk cache.
func CacheKey(name, pushedAt string) string { return name + "@" + pushedAt }

// LoadCache reads JSON cache; returns empty map on missing/corrupt file.
func LoadCache(path string) map[string][]string {
	out := map[string][]string{}
	data, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	_ = json.Unmarshal(data, &out)
	return out
}

// SaveCache writes the cache atomically (mkdir + sorted JSON).
func SaveCache(path string, cache map[string][]string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(cache, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".contributors-*.json.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		if rmErr := os.Remove(tmpName); rmErr != nil && !errors.Is(rmErr, os.ErrNotExist) {
			return fmt.Errorf("write temp cache: %w (cleanup temp file: %v)", err, rmErr)
		}
		return err
	}
	if err := tmp.Close(); err != nil {
		if rmErr := os.Remove(tmpName); rmErr != nil && !errors.Is(rmErr, os.ErrNotExist) {
			return fmt.Errorf("close temp cache: %w (cleanup temp file: %v)", err, rmErr)
		}
		return err
	}
	if err := os.Chmod(tmpName, 0o644); err != nil {
		if rmErr := os.Remove(tmpName); rmErr != nil && !errors.Is(rmErr, os.ErrNotExist) {
			return fmt.Errorf("chmod temp cache: %w (cleanup temp file: %v)", err, rmErr)
		}
		return err
	}
	return os.Rename(tmpName, path)
}

// Repo is the minimal interface a caller must provide for enrichment.
type Repo struct {
	Name     string
	PushedAt string
}

// Result is the per-repo enriched output.
type Result struct {
	Repo         Repo
	Contributors []string
}

// FetchFunc retrieves contributor logins via the gh REST endpoint.
type FetchFunc func(ctx context.Context, owner, name string) ([]string, error)

// ShellFetch is the production FetchFunc that shells out to gh api.
func ShellFetch(ctx context.Context, owner, name string) ([]string, error) {
	cmd := exec.CommandContext(ctx, "gh", "api",
		fmt.Sprintf("/repos/%s/%s/contributors?per_page=2", owner, name))
	out, err := cmd.Output()
	if err != nil {
		// 404, 403, timeout etc → empty (parity with Python contributors.py:84).
		var ee *exec.ExitError
		if errors.As(err, &ee) || errors.Is(err, context.DeadlineExceeded) {
			return nil, nil
		}
		return nil, err
	}
	var arr []struct {
		Login string `json:"login"`
	}
	if err := json.Unmarshal(out, &arr); err != nil {
		return nil, nil
	}
	logins := make([]string, 0, len(arr))
	for _, e := range arr {
		if e.Login != "" {
			logins = append(logins, e.Login)
		}
	}
	return StripBots(logins), nil
}

// Enrich fetches contributors for every repo (parallel, bounded).
// Cache hits skip network; misses go through fetch.
// Cache file is rewritten once at the end.
func Enrich(ctx context.Context, owner string, repos []Repo, cachePath string, fetch FetchFunc, maxWorkers int) ([]Result, error) {
	if maxWorkers < 1 {
		maxWorkers = 1
	}
	cache := LoadCache(cachePath)
	results := make([]Result, len(repos))
	var (
		mu       sync.Mutex
		newCache = map[string][]string{}
		wg       sync.WaitGroup
		sem      = make(chan struct{}, maxWorkers)
		firstErr error
	)
	for i, repo := range repos {
		wg.Add(1)
		go func(i int, repo Repo) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				mu.Lock()
				if firstErr == nil {
					firstErr = ctx.Err()
				}
				mu.Unlock()
				return
			}
			key := CacheKey(repo.Name, repo.PushedAt)
			mu.Lock()
			cached, ok := cache[key]
			mu.Unlock()
			var contribs []string
			if ok {
				contribs = append([]string(nil), cached...)
			} else {
				fetched, err := fetch(ctx, owner, repo.Name)
				if err != nil {
					mu.Lock()
					if firstErr == nil {
						firstErr = err
					}
					mu.Unlock()
					return
				}
				contribs = fetched
			}
			mu.Lock()
			newCache[key] = contribs
			results[i] = Result{Repo: repo, Contributors: contribs}
			mu.Unlock()
		}(i, repo)
	}
	wg.Wait()
	if firstErr != nil {
		return nil, firstErr
	}
	// Merge: existing cache entries we hit + new entries.
	for k, v := range newCache {
		cache[k] = v
	}
	if err := SaveCache(cachePath, cache); err != nil {
		return nil, fmt.Errorf("save cache: %w", err)
	}
	return results, nil
}
