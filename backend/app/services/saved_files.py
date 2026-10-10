"""Where a resource's saved file is on this machine.

The database records the path a file was saved to, but the data folder moves between
machines: a Windows laptop writes ``C:\\...\\downloads\\x.pdf`` and a Linux server
``/app/data/downloads/x.pdf``. Saved files sit directly in the downloads folder, so
when the recorded path is not here, the file's name finds it.
"""

from pathlib import Path, PureWindowsPath


def saved_file(local_path: str | None, downloads_dir: Path) -> Path | None:
    """The file for a recorded path, or None when nothing was recorded.

    The result may not exist: the caller checks, as it would for the recorded path.
    """

    if not local_path:
        return None
    recorded = Path(local_path)
    if recorded.is_file():
        return recorded
    # PureWindowsPath splits on both kinds of slash, so either machine's path works.
    name = PureWindowsPath(local_path).name
    return downloads_dir / name if name else None
