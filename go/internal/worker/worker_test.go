package worker

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"sync/atomic"
	"testing"
	"time"
)

func TestRunBasic(t *testing.T) {
	jobs := []int{1, 2, 3, 4, 5}
	out := Run(context.Background(), 2, jobs, func(_ context.Context, j int) (int, error) {
		return j * 2, nil
	})
	got := []int{}
	for r := range out {
		if r.Err != nil {
			t.Errorf("err: %v", r.Err)
		}
		got = append(got, r.Value)
	}
	sort.Ints(got)
	want := []int{2, 4, 6, 8, 10}
	for i := range got {
		if got[i] != want[i] {
			t.Fatalf("got %v want %v", got, want)
		}
	}
}

func TestRunPanicCaptured(t *testing.T) {
	jobs := []string{"good", "panic"}
	out := Run(context.Background(), 1, jobs, func(_ context.Context, j string) (int, error) {
		if j == "panic" {
			panic("boom")
		}
		return 1, nil
	})
	var panics int
	for r := range out {
		if r.Err != nil {
			var pe *PanicErr
			if errors.As(r.Err, &pe) {
				panics++
			}
		}
	}
	if panics != 1 {
		t.Errorf("want 1 panic err, got %d", panics)
	}
}

func TestRunCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	jobs := make([]int, 100)
	for i := range jobs {
		jobs[i] = i
	}
	var started int32
	out := Run(ctx, 2, jobs, func(c context.Context, j int) (int, error) {
		atomic.AddInt32(&started, 1)
		select {
		case <-c.Done():
			return 0, c.Err()
		case <-time.After(50 * time.Millisecond):
		}
		return j, nil
	})
	cancel()
	for range out {
	}
}

func TestRunEmpty(t *testing.T) {
	out := Run(context.Background(), 4, []int{}, func(context.Context, int) (int, error) { return 0, nil })
	for range out {
		t.Fatal("should not yield")
	}
}

func TestRunWorkerErrPropagates(t *testing.T) {
	out := Run(context.Background(), 1, []int{1}, func(context.Context, int) (int, error) {
		return 0, fmt.Errorf("nope")
	})
	r := <-out
	if r.Err == nil {
		t.Error("want err")
	}
}

func TestPanicErr(t *testing.T) {
	e := &PanicErr{Value: "x"}
	if e.Error() == "" {
		t.Error("empty msg")
	}
}
