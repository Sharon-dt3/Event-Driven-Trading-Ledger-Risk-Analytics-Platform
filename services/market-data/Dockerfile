# Build context is the parent `services/` directory (see infra/docker-compose.yml)
# so the shared `common-go` module referenced via a local replace is available.
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY common-go/ ./common-go/
COPY market-data/go.mod ./market-data/go.mod
WORKDIR /app/market-data
RUN go mod download
COPY market-data/ /app/market-data/
RUN CGO_ENABLED=0 go build -o /bin/market-data .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /bin/market-data /bin/market-data
EXPOSE 8081
ENTRYPOINT ["/bin/market-data"]
