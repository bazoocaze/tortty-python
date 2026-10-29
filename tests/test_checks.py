"""Bateria de testes: uma função por área crítica, sem display."""

import pytest

from bzmux.checks import ALL


@pytest.mark.parametrize("check", ALL, ids=[c.__name__ for c in ALL])
def test_check(check):
    check()
