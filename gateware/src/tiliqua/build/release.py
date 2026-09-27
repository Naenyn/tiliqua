"""Resolve product release tags without changing the bootloader tag format."""

import re


PRODUCT_TAG = re.compile(r"^(?P<product>[a-z0-9]+)-(?P<version>v\d+\.\d+\.\d+)$")
GLOBAL_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


def source_label(repo, product_name, max_length):
    """Return (display tag, full release tag), or a short commit label.

    Several products may have tags at the same commit. A build only adopts the
    tag matching its bitstream name; the archive stem already names the product.
    """
    commit = repo.head.commit.hexsha
    if repo.is_dirty():
        return f"{commit[:max_length - 2]}-d", None

    product = product_name.lower()
    tags = repo.git.tag("--points-at", "HEAD").splitlines()
    releases = []
    for tag in tags:
        match = PRODUCT_TAG.fullmatch(tag)
        if match and match.group("product") == product:
            releases.append((tag, match.group("version")))
    if len(releases) > 1:
        raise ValueError(f"multiple {product} release tags point at HEAD: "
                         + ", ".join(tag for tag, _ in releases))
    if releases:
        tag, version = releases[0]
        if len(version) > max_length:
            raise ValueError(f"release version {version!r} exceeds the "
                             f"{max_length}-character bitstream tag limit")
        return version, tag

    # Preserve upstream's unprefixed release tags for upstream bitstreams.
    global_tags = [tag for tag in tags if GLOBAL_TAG.fullmatch(tag)]
    if len(global_tags) == 1 and len(global_tags[0]) <= max_length:
        return global_tags[0], global_tags[0]
    return commit[:max_length], None
