"""Runner sem dependências dos checks: python3 -m tortty_python --selftest."""

import sys
import traceback

from .checks import ALL


def selftest():
    """Roda todos os checks e imprime ok/FAIL por nome."""
    fails = 0
    for check in ALL:
        name = check.__name__
        try:
            check()
        except AssertionError:
            fails += 1
            tb = traceback.extract_tb(sys.exc_info()[2])[-1]
            print(f"  FAIL: {name} ({tb.filename}:{tb.lineno})")
        else:
            print(f"  ok: {name}")
    if fails:
        print(f"SELFTEST FAIL ({fails}/{len(ALL)})")
        return 1
    print(f"SELFTEST OK ({len(ALL)} checks)")
    return 0
