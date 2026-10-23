"""Choose GHCR tags; latest belongs to the highest stable vMAJOR.MINOR.PATCH."""

import os
import re
import subprocess
from pathlib import Path

STABLE = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
RELEASE = re.compile(STABLE.pattern + r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")


def image_tags(repository: str, tag: str, existing_tags: list[str]) -> list[str]:
    if not RELEASE.fullmatch(tag) or len(tag) > 128:
        raise ValueError("Expected vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-prerelease")
    image = f"ghcr.io/{repository.lower()}"
    result = [f"{image}:{tag[1:]}"]
    stable = STABLE.fullmatch(tag)
    if stable:
        version = tuple(map(int, stable.groups()))
        versions = [
            tuple(map(int, match.groups()))
            for candidate in existing_tags
            if (match := STABLE.fullmatch(candidate))
        ]
        if version >= max(versions, default=version):
            result.append(f"{image}:latest")
    return result


if __name__ == "__main__":
    tags = subprocess.check_output(["git", "tag", "--list"], text=True).splitlines()
    selected = image_tags(
        os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF_NAME"], tags
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("tags<<EOF\n" + "\n".join(selected) + "\nEOF\n")
