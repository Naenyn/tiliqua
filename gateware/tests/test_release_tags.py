"""Product tags sharing one commit must package independently."""

import json
import subprocess
import tarfile
from pathlib import Path

import git
import pytest

from tiliqua.build.archive import ArchiveBuilder
from tiliqua.build.release import source_label
from tiliqua.flash.archive_loader import ArchiveLoader
from tiliqua.platform import TiliquaRevision


def git_command(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


@pytest.fixture
def tagged_repo(tmp_path):
    git_command(tmp_path, "init", "-q")
    git_command(tmp_path, "config", "user.name", "Test")
    git_command(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "source.txt").write_text("source\n")
    git_command(tmp_path, "add", "source.txt")
    git_command(tmp_path, "commit", "-qm", "source")
    for product, version in (
        ("oscio", "v1.1.0"), ("sonoro", "v1.1.0"),
        ("cascado", "v1.0.0"), ("rezo", "v1.0.0"),
        ("strezo", "v1.0.0"), ("rezomo", "v1.0.0"),
    ):
        git_command(tmp_path, "tag", f"{product}-{version}")
    return git.Repo(tmp_path)


def test_product_tags_on_same_commit(tagged_repo):
    for product, version in (("OSCIO", "v1.1.0"), ("SONORO", "v1.1.0"),
                             ("REZO", "v1.0.0"), ("REZOMO", "v1.0.0")):
        assert source_label(tagged_repo, product, 8) == (
            version, f"{product.lower()}-{version}")
    assert source_label(tagged_repo, "INTONO", 8) == (
        tagged_repo.head.commit.hexsha[:8], None)


def test_ambiguous_and_dirty_release_labels(tagged_repo):
    git_command(tagged_repo.working_tree_dir, "tag", "oscio-v1.1.1")
    with pytest.raises(ValueError, match="multiple oscio release tags"):
        source_label(tagged_repo, "OSCIO", 8)
    source = Path(tagged_repo.working_tree_dir) / "source.txt"
    source.write_text("modified\n")
    label, full_tag = source_label(tagged_repo, "OSCIO", 8)
    assert label.endswith("-d") and full_tag is None


def test_archive_keeps_existing_layout_and_includes_provenance(tmp_path):
    build_path = tmp_path / "build"
    build_path.mkdir()
    (build_path / "top.bit").write_bytes(b"bitstream")
    info = {"git_commit": "a" * 40, "git_tag": "sonoro-v1.1.0",
            "display_tag": "v1.1.0", "audio_clock_hz": 49_152_000}
    archive = ArchiveBuilder(
        build_path=str(build_path), name="SONORO", tag="v1.1.0",
        hw_rev=TiliquaRevision.R5, build_info=info,
    )
    assert archive.with_bitstream().create()
    assert archive.archive_name == "sonoro-v1.1.0-r5.tar.gz"
    with tarfile.open(archive.archive_path) as contents:
        assert {member.name for member in contents} == {
            "top.bit", "manifest.json", "build-info.json"}
        assert json.load(contents.extractfile("manifest.json"))["tag"] == "v1.1.0"
        assert json.load(contents.extractfile("build-info.json")) == info
    with ArchiveLoader(archive.archive_path) as loader:
        assert loader.manifest.tag == "v1.1.0"
