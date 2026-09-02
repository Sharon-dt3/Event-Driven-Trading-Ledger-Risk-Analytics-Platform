# Build context is the parent `services/` directory (see infra/docker-compose.yml)
# so the shared `common-go` module referenced via a local replace is available.
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY common-go/ ./common-go/
COPY gateway/go.mod ./gateway/go.mod
WORKDIR /app/gateway
RUN go mod download
COPY gateway/ /app/gateway/
RUN CGO_ENABLED=0 go build -o /bin/gateway .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /bin/gateway /bin/gateway
EXPOSE 8084
ENTRYPOINT ["/bin/gateway"]
