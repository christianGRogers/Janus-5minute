.PHONY: build run clean install-deps fmt lint

# Build the bot
build:
	go build -o janus-bot ./cmd/bot

# Run the bot
run: build
	./janus-bot

# Development run (direct)
dev:
	go run ./cmd/bot

# Install dependencies
install-deps:
	go mod download
	go mod tidy

# Format code
fmt:
	go fmt ./...

# Run linter (requires golangci-lint)
lint:
	golangci-lint run ./...

# Clean build artifacts
clean:
	rm -f janus-bot
	go clean

# Run tests (when added)
test:
	go test -v ./...

# Help
help:
	@echo "Available targets:"
	@echo "  make build       - Build the bot"
	@echo "  make run         - Build and run the bot"
	@echo "  make dev         - Run directly for development"
	@echo "  make install-deps - Install dependencies"
	@echo "  make fmt         - Format code"
	@echo "  make lint        - Run linter"
	@echo "  make clean       - Clean build artifacts"
	@echo "  make test        - Run tests"
