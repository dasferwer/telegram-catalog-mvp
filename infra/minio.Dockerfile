FROM golang:1.27-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5 AS build
WORKDIR /src
ADD --checksum=sha256:71794c2df26aad0cc99e8421c58b7aa2dd55969f979b0e7d1e931042e9fabcd6 https://codeload.github.com/minio/minio/tar.gz/7aac2a2c5b7c882e68c1ce017d8256be2feea27f /tmp/source.tar.gz
RUN tar -xzf /tmp/source.tar.gz --strip-components=1 -C /src
COPY infra/minio/go.mod infra/minio/go.sum ./
RUN --mount=type=cache,id=catalog-go-mod,target=/go/pkg/mod --mount=type=cache,id=catalog-go-build,target=/root/.cache/go-build CGO_ENABLED=0 GOTOOLCHAIN=local go build -mod=readonly -trimpath -o /out/minio .
COPY infra/storage-init.go /src/catalog-init/main.go
COPY infra/healthcheck.go /src/catalog-health/main.go
RUN --mount=type=cache,id=catalog-go-mod,target=/go/pkg/mod --mount=type=cache,id=catalog-go-build,target=/root/.cache/go-build CGO_ENABLED=0 GOTOOLCHAIN=local go build -mod=readonly -trimpath -o /out/storage-init ./catalog-init && CGO_ENABLED=0 GOTOOLCHAIN=local go build -mod=readonly -trimpath -o /out/healthcheck ./catalog-health
FROM scratch AS base
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
FROM base AS minio
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /out/healthcheck /usr/local/bin/healthcheck
COPY --from=build /src/LICENSE /src/NOTICE /licenses/
ENV HOME=/data
USER 10001:10001
EXPOSE 9000
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]

FROM base AS storage-init
COPY --from=build /out/storage-init /usr/local/bin/storage-init
COPY --from=build /src/LICENSE /src/NOTICE /licenses/
USER 10001:10001
ENTRYPOINT ["storage-init"]
