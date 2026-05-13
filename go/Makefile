SHELL := /bin/bash

.PHONY: build test test-race coverage-gate lint fmt vet tidy clean golden-update release-snapshot release-dry-run release

BIN := writeme
CMD := ./cmd/writeme
ROOT := ..

VERSION_LDFLAGS := -s -w -X main.version=$$(git -C $(ROOT) describe --tags --always --dirty 2>/dev/null || echo dev) -X main.commit=$$(git -C $(ROOT) rev-parse --short HEAD 2>/dev/null || echo unknown) -X main.date=$$(date -u +%Y-%m-%dT%H:%M:%SZ)

build:
	go build -ldflags "$(VERSION_LDFLAGS)" -o $(BIN) $(CMD)

test:
	go test -cover ./...

test-race:
	go test -race -cover ./...

coverage-gate:
	set -o pipefail; go test -cover ./... 2>&1 | tee coverage.txt
	bash scripts/coverage_gate.sh coverage.txt

vet:
	go vet ./...

fmt:
	gofmt -w .

lint:
	golangci-lint run ./...

tidy:
	go mod tidy

clean:
	rm -f $(BIN) coverage.txt cover.out

golden-update:
	cd $(ROOT) && python3 go/testdata/capture_goldens.py

release-snapshot:
	cd $(ROOT) && goreleaser release --snapshot --clean --skip=sign,sbom

release-dry-run:
	cd $(ROOT) && goreleaser release --snapshot --clean --skip=sign,sbom,publish

release:
	cd $(ROOT) && goreleaser release --clean
