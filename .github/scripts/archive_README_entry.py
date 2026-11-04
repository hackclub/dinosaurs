#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


DESCRIPTION_RE = re.compile(r'^\s*"([^"]*)"\s*$')

IMAGE_RE = re.compile(
    r'!\[[^\]]*\]\s*\\?\(\s*(?:<([^>]+)>|([^\s)]+))\s*\\?\)'
)

ARCHIVE_PATH_RE = re.compile(
    r"^(20\d{2})/([^/]+)/.+$"
)


@dataclass
class Entry:
    start: int
    end: int
    description: str
    text: str
    image_paths: list[str]


# ---------------------------------------------------------------------------
# Path handling
# ---------------------------------------------------------------------------

def normalize_image_path(path: str) -> str:
    """
    Normalize a repository-relative Markdown image path.

    These all become:

        2026/August/dino.png

        2026/August/dino.png
        /2026/August/dino.png
        ./2026/August/dino.png
        .//2026/August/dino.png

    URLs are left untouched.
    """

    path = path.strip()

    # Don't reinterpret URLs as repository paths.
    if re.match(
        r"^[a-zA-Z][a-zA-Z0-9+.-]*://",
        path,
    ):
        return path

    while path.startswith("./"):
        path = path[2:]

    return path.lstrip("/")


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )

    return result.stdout


def repo_root() -> Path:
    return Path(
        git(
            Path(__file__).resolve().parent,
            "rev-parse",
            "--show-toplevel",
        ).strip()
    ).resolve()


def build_git_index(
    root: Path,
) -> dict[str, datetime]:
    """
    Map filenames to the earliest date Git saw them.

    We deliberately use filenames rather than current paths because the
    dinosaur reorganization moves files from the repository root into
    YYYY/Month/ directories.
    """

    output = git(
        root,
        "log",
        "--all",
        "--reverse",
        "--find-renames",
        "--find-copies",
        "--format=%cI",
        "--name-status",
    )

    index: dict[str, datetime] = {}
    date: datetime | None = None

    for line in output.splitlines():
        if not line:
            continue

        # Commit date.
        if "\t" not in line:
            try:
                date = datetime.fromisoformat(line)
            except ValueError:
                pass

            continue

        parts = line.split("\t")

        if date is None or len(parts) < 2:
            continue

        status = parts[0]

        if status == "A":
            index.setdefault(
                Path(parts[1]).name,
                date,
            )

        elif status.startswith(("R", "C")) and len(parts) >= 3:
            # Record both sides of renames/copies.
            index.setdefault(
                Path(parts[1]).name,
                date,
            )
            index.setdefault(
                Path(parts[2]).name,
                date,
            )

    return index


# ---------------------------------------------------------------------------
# README parsing
# ---------------------------------------------------------------------------

def parse_entries(text: str) -> list[Entry]:
    """
    Parse entries of the form:

        "description"

        ![](2026/August/dino.png)

    Blank lines between the description and image are allowed.

    An image without a preceding quoted description is ignored.
    """

    lines = text.splitlines(keepends=True)

    offsets: list[int] = []
    offset = 0

    for line in lines:
        offsets.append(offset)
        offset += len(line)

    entries: list[Entry] = []

    for i, line in enumerate(lines):
        match = DESCRIPTION_RE.match(line)

        if not match:
            continue

        description = match.group(1).strip()

        # Find the next non-empty line.
        j = i + 1

        while j < len(lines) and not lines[j].strip():
            j += 1

        if j >= len(lines):
            continue

        image_paths: list[str] = []

        for image_match in IMAGE_RE.finditer(lines[j]):
            path = (
                image_match.group(1)
                or image_match.group(2)
            )

            if not path:
                continue

            path = normalize_image_path(path)

            # Only accept repository archive paths such as:
            #
            #   2026/August/foo.png
            #
            # Not arbitrary URLs containing those words.
            if ARCHIVE_PATH_RE.match(path):
                image_paths.append(path)

        if not image_paths:
            continue

        start = offsets[i]
        end = offsets[j] + len(lines[j])

        entries.append(
            Entry(
                start=start,
                end=end,
                description=description,
                text=text[start:end].rstrip(),
                image_paths=image_paths,
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Archive destination
# ---------------------------------------------------------------------------

def destination(
    root: Path,
    entry: Entry,
) -> Path | None:
    """
    Determine the YYYY/Month README for an entry.

    All images in an entry must belong to the same month.
    """

    locations: set[tuple[str, str]] = set()

    for path in entry.image_paths:
        match = ARCHIVE_PATH_RE.match(path)

        if match:
            locations.add(
                (match.group(1), match.group(2))
            )

    if len(locations) != 1:
        return None

    year, month = locations.pop()

    return root / year / month / "README.md"


# ---------------------------------------------------------------------------
# Image path rewriting
# ---------------------------------------------------------------------------

def rewrite_paths(
    text: str,
    image_paths: list[str],
) -> str:
    """
    Convert repository paths into paths relative to the monthly README.

    Example:

        ![](/2026/August/dino.png)

    becomes:

        ![](dino.png)
    """

    replacements = {
        path: Path(path).name
        for path in image_paths
    }

    def replace(match: re.Match[str]) -> str:
        path = (
            match.group(1)
            or match.group(2)
        )

        normalized = normalize_image_path(path)

        if normalized not in replacements:
            return match.group(0)

        new_path = replacements[normalized]

        if match.group(1) is not None:
            return match.group(0).replace(
                f"<{path}>",
                f"<{new_path}>",
                1,
            )

        return match.group(0).replace(
            path,
            new_path,
            1,
        )

    return IMAGE_RE.sub(
        replace,
        text,
    )


# ---------------------------------------------------------------------------
# README insertion
# ---------------------------------------------------------------------------

def insert_before_footer(
    original: str,
    snippet: str,
) -> str:
    """
    Insert an entry immediately before the README footer.

    If no footer exists, append the entry.
    """

    lines = original.splitlines(keepends=True)

    footer = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip() in {
                "---",
                "***",
                "___",
            }
        ),
        None,
    )

    if footer is None:
        return (
            original.rstrip()
            + "\n\n"
            + snippet.strip()
            + "\n"
        )

    before = "".join(
        lines[:footer]
    ).rstrip()

    after = "".join(
        lines[footer:]
    ).lstrip("\n")

    return (
        before
        + "\n\n"
        + snippet.strip()
        + "\n\n"
        + after
    ).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive old dinosaur entries."
    )

    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help=(
            "Archive entries older than this many "
            "days (default: 14)."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show what would be archived without "
            "modifying files."
        ),
    )

    args = parser.parse_args()

    if args.days < 0:
        parser.error(
            "--days must be non-negative"
        )

    root = repo_root()
    readme = root / "README.md"

    text = readme.read_text(
        encoding="utf-8"
    )

    entries = parse_entries(text)

    print(
        f"Found {len(entries)} candidate "
        f"entr{'y' if len(entries) == 1 else 'ies'}."
    )

    if not entries:
        return

    # Build the Git history once rather than running git log separately for
    # every dinosaur.
    git_index = build_git_index(root)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(
        days=args.days
    )

    archive: list[
        tuple[Entry, Path, datetime]
    ] = []

    for entry in entries:
        added_dates = [
            git_index[filename]
            for filename in (
                Path(path).name
                for path in entry.image_paths
            )
            if filename in git_index
        ]

        if not added_dates:
            print(
                "WARNING: could not determine "
                "Git age; skipping:"
            )
            print(
                f"  {entry.description}"
            )
            continue

        added = min(added_dates)

        if added > cutoff:
            continue

        target = destination(
            root,
            entry,
        )

        if target is None:
            print(
                "WARNING: could not determine a "
                "single destination; skipping:"
            )
            print(
                f"  {entry.description}"
            )
            continue

        # Never create missing READMEs.
        if not target.exists():
            print(
                "WARNING: destination README "
                "does not exist; skipping:"
            )
            print(
                f"  {target.relative_to(root)}"
            )
            continue

        archive.append(
            (entry, target, added)
        )

    if not archive:
        print("Nothing to archive.")
        return

    print(
        f"Found {len(archive)} archiveable "
        f"entr{'y' if len(archive) == 1 else 'ies'}:\n"
    )

    for entry, target, added in archive:
        age = now - added

        print(
            f"  {entry.description}"
        )
        print(
            f"    added:       {added.isoformat()}"
        )
        print(
            f"    age:         {age.days} days"
        )
        print(
            f"    destination: "
            f"{target.relative_to(root)}"
        )
        print()

    if args.dry_run:
        print(
            "Dry run: no files were modified."
        )
        return

    # -----------------------------------------------------------------------
    # Add entries to monthly READMEs.
    #
    # Deliberately no duplicate detection. If two entries exist, both are
    # archived.
    # -----------------------------------------------------------------------

    by_target: dict[
        Path,
        list[Entry],
    ] = {}

    for entry, target, _ in archive:
        by_target.setdefault(
            target,
            [],
        ).append(entry)

    for target, target_entries in by_target.items():
        target_text = target.read_text(
            encoding="utf-8"
        )

        for entry in target_entries:
            snippet = rewrite_paths(
                entry.text,
                entry.image_paths,
            )

            target_text = insert_before_footer(
                target_text,
                snippet,
            )

        target.write_text(
            target_text,
            encoding="utf-8",
        )

    # -----------------------------------------------------------------------
    # Remove archived entries from the root README.
    #
    # Work backwards so earlier character offsets remain valid.
    # -----------------------------------------------------------------------

    for entry, _, _ in reversed(archive):
        text = (
            text[:entry.start]
            + text[entry.end:]
        )

    # Avoid accumulating huge blank-line gaps.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    ).rstrip() + "\n"

    readme.write_text(
        text,
        encoding="utf-8",
    )

    print(
        f"Archived {len(archive)} entries."
    )


if __name__ == "__main__":
    main()