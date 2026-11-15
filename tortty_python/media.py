"""The bytes a kitty transmission by file or shared memory names (`t=f`/`t=t`/`t=s`).

Pure stdlib and no display, so `--selftest` can exercise the only place that
opens a path the child chose: the ceiling and the `t=t` delete are the contract.
"""

import os

MEDIA_MAX = 32 << 20  # a real picture is far below; 32 MB keeps a hostile one out


def load(path, delete=False):
    """Read `path` (a `~` expanded, `/dev/shm` included), or None.

    `delete` is the `t=t` contract: the file is the terminal's to remove once
    read, whether the bytes were usable or not.
    """
    if not path:
        return None
    p = os.path.expanduser(path)
    try:
        with open(p, "rb") as f:
            data = f.read(MEDIA_MAX + 1)
    except (OSError, ValueError):
        return None
    finally:
        if delete:
            try:
                os.unlink(p)
            except OSError:
                pass
    return data if len(data) <= MEDIA_MAX else None
