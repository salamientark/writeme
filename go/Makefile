.PHONY: build test test-race lint fmt vet tidy clean golden-update

BIN := writeme
CMD := ./cmd/writeme

build:
	go build -o $(BIN) $(CMD)

test:
	go test -cover ./...

test-race:
	go test -race -cover ./...

vet:
	go vet ./...

fmt:
	gofmt -w .

lint:
	golangci-lint run ./...

tidy:
	go mod tidy

clean:
	rm -f $(BIN)

golden-update:
	cd .. && python3 go/testdata/capture_goldens.py
