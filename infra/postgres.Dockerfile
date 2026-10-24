FROM golang:1.27-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5 AS gosu
WORKDIR /src
ADD --checksum=sha256:33d7537d588ea49458b9509bcf4554bdf5ceacc66da71e5caa1058ea3b689c3b https://codeload.github.com/tianon/gosu/tar.gz/6456aaa0f3c854d199d0f037f068eb97515b7513 /tmp/gosu.tar.gz
RUN tar -xzf /tmp/gosu.tar.gz --strip-components=1 -C /src
COPY infra/gosu/go.mod infra/gosu/go.sum ./
RUN CGO_ENABLED=0 GOTOOLCHAIN=local go build -mod=readonly -trimpath -o /out/gosu .

FROM postgres:17-trixie@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe
COPY --from=gosu /out/gosu /usr/local/bin/gosu
COPY --from=gosu /src/LICENSE /licenses/gosu/LICENSE
