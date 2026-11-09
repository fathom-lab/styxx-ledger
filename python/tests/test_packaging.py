"""packaging and checkout hygiene (improvements 2026-11-09, ranks 46, 47, 64, 65 and 66).

46: each package ships the MIT text: python/LICENSE and js/LICENSE are byte copies of the repository's LICENSE, named
by the pyproject's license-files and js/package.json's files. 47: the pyproject uses the pep 639 form (an spdx string,
license-files, setuptools>=77 to build it, no license classifier); the table form setuptools deprecated, with its
removal dated 2027-02-18, is gone. 64: the package readmes, which pypi and npm show without the repository around
them, carry no `../` path, every relative-looking link is absolute, and every github link names a file or folder in
this checkout. 65: python-version classifiers that agree with requires-python, homepage, repository and issues urls
on both registries, one keyword list for both. 66: the kit root's .gitignore hides what the README's own steps leave
in a checkout, and no tracked file.

the pyproject is read as text, not with tomllib, so the file runs on python 3.10 (which has no tomllib) like the rest
of the suite. the git checks skip outside a git checkout or without git on PATH; they read only the kit's own
.gitignore, never a global excludes file.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import JS, PYROOT, REPO

REPO_URL = "https://github.com/fathom-lab/styxx-ledger"
PYPROJECT = (PYROOT / "pyproject.toml").read_text(encoding="utf-8")
PKG = json.loads((JS / "package.json").read_text(encoding="utf-8"))
README_LINK = re.compile(re.escape(REPO_URL) + r"/(blob|tree)/main/([^)\s#>]+)")


def _toml_line(key):
    m = re.search(r"(?m)^%s = (.+)$" % re.escape(key), PYPROJECT)
    assert m, "pyproject.toml has no top-level line for %s" % key
    return m.group(1)


def test_each_package_carries_a_byte_copy_of_the_license():
    root = REPO / "LICENSE"
    if not root.is_file():
        pytest.skip("no repository LICENSE beside the package (not a checkout)")
    want = root.read_bytes()
    assert want.startswith(b"MIT License\n")
    for copy in (PYROOT / "LICENSE", JS / "LICENSE"):
        assert copy.is_file(), "%s is missing" % copy
        assert copy.read_bytes() == want, "%s differs from the repository's LICENSE" % copy
    assert _toml_line("license-files") == '["LICENSE"]'
    assert "LICENSE" in PKG["files"]


def test_the_pyproject_license_is_the_pep639_form():
    assert _toml_line("license") == '"MIT"'
    assert not re.search(r"(?m)^license = \{", PYPROJECT), "the deprecated table form is back"
    assert "License ::" not in PYPROJECT, "a license classifier beside an spdx license is refused by setuptools>=77"
    m = re.search(r'(?m)^requires = \["setuptools>=([0-9]+)', PYPROJECT)
    assert m and int(m.group(1)) >= 77, "setuptools before 77 cannot read license = \"MIT\" with license-files"
    assert PKG["license"] == "MIT"


def test_the_python_version_classifiers_agree_with_requires_python():
    floor = re.fullmatch(r'">=3\.([0-9]+)"', _toml_line("requires-python"))
    assert floor, "requires-python is not of the form >=3.N"
    minors = [int(v) for v in re.findall(r'"Programming Language :: Python :: 3\.([0-9]+)"', PYPROJECT)]
    assert minors, "no python-version classifiers"
    assert minors[0] == int(floor.group(1)), "the lowest classifier is not requires-python's floor"
    assert minors == list(range(minors[0], minors[-1] + 1)), "the version classifiers skip a version"
    assert '"Programming Language :: Python :: 3 :: Only"' in PYPROJECT


def test_both_registries_get_urls_author_and_one_keyword_list():
    for label in ("Homepage", "Repository", "Issues"):
        url = json.loads(_toml_line(label))
        assert url.startswith(REPO_URL), (label, url)
    assert json.loads(_toml_line("Issues")) == REPO_URL + "/issues"
    assert PKG["repository"]["url"] == REPO_URL + ".git" and PKG["repository"]["directory"] == "js"
    assert PKG["homepage"].startswith(REPO_URL + "/")
    assert PKG["bugs"]["url"] == REPO_URL + "/issues"
    assert PKG["author"], "package.json names no author"
    assert re.search(r'(?m)^authors = \[\{name = "%s"\}\]$' % re.escape(PKG["author"]), PYPROJECT), \
        "the two registries name different authors"
    assert PKG["engines"]["node"] == ">=20"
    py_keywords = json.loads(_toml_line("keywords"))
    assert py_keywords == PKG["keywords"], "the two registries list different keywords"
    for k in ("append-only", "tamper-evident", "opentimestamps", "hash-chain"):
        assert k in py_keywords, k


@pytest.mark.parametrize("readme", [PYROOT / "README.md", JS / "README.md"], ids=["python", "js"])
def test_a_package_readme_links_only_what_its_package_carries(readme):
    text = readme.read_text(encoding="utf-8")
    assert "../" not in text, "a ../ path is dead text on pypi and npm: link the file on github instead"
    for target in re.findall(r"\]\(([^)]*)\)", text):
        assert target.startswith("https://"), "relative link %r is dead on the registry" % target
    links = README_LINK.findall(text)
    assert links, "no github link at all"
    if not (REPO / "PROTOCOL_v1.md").is_file():
        pytest.skip("not a checkout: the linked files are not here to check")
    for kind, rel in links:
        p = REPO / rel
        assert (p.is_file() if kind == "blob" else p.is_dir()), "%s links %s/%s, which this checkout lacks" % (
            readme.name, kind, rel)


def _git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=60)


def test_the_gitignore_hides_the_readme_leftovers_and_no_tracked_file():
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    top = _git("rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != REPO.resolve():
        pytest.skip("not the kit's own git checkout")
    leftovers = [
        "python/build/lib/styxx_ledger/cli.py",              # pip install ./python builds in place
        "python/src/styxx_ledger.egg-info/PKG-INFO",
        "dist/styxx_ledger-1.0.0a2.tar.gz",                 # python -m build
        "js/styxx-ledger-%s.tgz" % PKG["version"],          # npm pack
        ".venv/pyvenv.cfg",                                 # the README's venv route
        "census_rehearsal/RESULT.json",                     # the README's census rehearsal
        "python/tests/__pycache__/conftest.cpython-312.pyc",
        "census/.pytest_cache/README.md",
    ]
    for rel in leftovers:
        cp = _git("check-ignore", "-v", "--no-index", rel)
        assert cp.returncode == 0, "%s is not ignored" % rel
        assert cp.stdout.split(":", 1)[0] == ".gitignore", "%s is ignored by %s, not the kit's .gitignore" % (
            rel, cp.stdout.strip())
    cp = _git("ls-files", "-ci", "--exclude-per-directory=.gitignore")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "", "tracked files the .gitignore would hide:\n" + cp.stdout
