# Development and releases

[Back to README](../README.md)

## Local checks

```sh
uv sync --frozen --group dev --extra exporter
uv run --no-sync pytest -q
uv run --no-sync ruff check . .github/image_tags.py
uv build
```

The tests use local HTTP servers and simulated switch responses. They do not
need access to a physical switch or credentials.

## CI and releases

GitHub Actions tests Python 3.11–3.14, runs Ruff, builds the wheel and source
distribution (available as the `distributions` workflow artifact), and builds
the exporter image on branch pushes and pull requests. Tests use simulated
switches; no switch credentials are needed in CI.

Push a version tag such as `v0.1.0` to publish the image to
`ghcr.io/OWNER/REPOSITORY:0.1.0` after checks pass. Update the package version
in `pyproject.toml` and run `uv lock` before tagging a release. The workflow
authenticates using the repository's `GITHUB_TOKEN` with `packages: write`.
It does not publish to PyPI.

The `latest` image tag is updated only when the release is the highest stable
`vMAJOR.MINOR.PATCH` tag in the repository. Older releases and prereleases
(for example `v0.2.0-rc.1`) publish only their version tag. Image publishing is
serialized to prevent concurrent releases from moving `latest` backwards.

## Container build

The Dockerfile installs the optional exporter dependency and runs as UID/GID
10001. The build context allowlist includes only the Dockerfile, package
sources, and metadata, keeping local credentials and development files out
of the image.
