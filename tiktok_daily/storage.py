import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def empty_state():
    return {"version": 1, "entries": {}, "image_requests": {}, "text_requests": {}}


class LocalStore:
    def __init__(self, directory):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)
        file = self.path / "state.json"
        self.state = json.loads(file.read_text()) if file.exists() else empty_state()
        if self.state.get("version") != 1:
            raise RuntimeError("Unsupported state version")

    def checkpoint(self):
        target = self.path / "state.json"
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)

    def save_image(self, filename, data):
        path = self.path / "images" / filename
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        return path


class GitStore(LocalStore):
    """Push every checkpoint BEFORE remote side effects. Never force-push."""

    def __init__(self, root, branch, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid GITHUB_REPOSITORY")
        self.root, self.branch, self.repository = Path(root), branch, repository
        remote = self.git("remote", "get-url", "origin")
        if remote.strip().removesuffix(".git") != f"https://github.com/{repository}":
            raise RuntimeError("Use the standard HTTPS GitHub checkout remote")
        self.directory = Path(tempfile.mkdtemp(prefix="tiktok-state-"))
        refs = self.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
        if refs.strip():
            self.git("fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}")
            self.git("worktree", "add", "--detach", str(self.directory), f"refs/remotes/origin/{branch}")
        else:
            self.git("worktree", "add", "--orphan", "-b", branch, str(self.directory))
        super().__init__(self.directory)

    def git(self, *args, directory=None):
        result = subprocess.run(["git", "-C", str(directory or self.root), *args],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            # Git errors can contain auth URLs; never emit its stderr.
            raise RuntimeError(f"Git operation {args[0]} failed; check branch permissions/remote")
        return result.stdout

    def checkpoint(self):
        super().checkpoint()
        self.git("add", "state.json", directory=self.path)
        if (self.path / "images").exists():
            self.git("add", "images", directory=self.path)
        if self.git("diff", "--cached", "--name-only", directory=self.path).strip():
            self.git("-c", "user.name=Daily Image Bot", "-c", "user.email=daily-image-bot@users.noreply.github.com",
                     "commit", "-m", "Save daily publishing checkpoint [skip ci]", directory=self.path)
        self.git("push", "origin", f"HEAD:refs/heads/{self.branch}", directory=self.path)

    def image_url(self, filename):
        # A commit SHA is immutable, avoiding stale branch media caches.
        sha = self.git("rev-parse", "HEAD", directory=self.path).strip()
        return f"https://raw.githubusercontent.com/{self.repository}/{sha}/images/{filename}"

    def close(self):
        self.git("worktree", "remove", "--force", str(self.directory))
