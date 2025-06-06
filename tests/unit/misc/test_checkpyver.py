# SPDX-FileCopyrightText: Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.misc.checkpyver."""

import re
import sys
import subprocess
import unittest.mock

import pytest

from qutebrowser.misc import checkpyver


TEXT = (r"At least Python 3.9 is required to run qutebrowser, but it's "
        r"running with \d+\.\d+\.\d+.")


@pytest.mark.not_frozen
@pytest.mark.parametrize('python', ['python2', 'python3.6'])
def test_old_python(python):
    """Run checkpyver with old python versions."""
    try:
        proc = subprocess.run(
            [python, checkpyver.__file__, '--no-err-windows'],
            capture_output=True,
            check=False)
    except FileNotFoundError:
        pytest.skip(f"{python} not found")
    assert not proc.stdout
    stderr = proc.stderr.decode('utf-8').rstrip()
    assert re.fullmatch(TEXT, stderr), stderr
    assert proc.returncode == 1


def test_normal(capfd):
    checkpyver.check_python_version()
    out, err = capfd.readouterr()
    assert not out
    assert not err


def test_patched_no_errwindow(capfd, monkeypatch):
    """Test with a patched sys.hexversion and --no-err-windows."""
    monkeypatch.setattr(checkpyver.sys, 'argv',
                        [sys.argv[0], '--no-err-windows'])
    monkeypatch.setattr(checkpyver.sys, 'hexversion', 0x03040000)
    monkeypatch.setattr(checkpyver.sys, 'exit', lambda status: None)
    checkpyver.check_python_version()

    stdout, stderr = capfd.readouterr()
    stderr = stderr.rstrip()
    assert not stdout
    assert re.fullmatch(TEXT, stderr), stderr


def test_patched_errwindow(capfd, mocker, monkeypatch):
    """Test with a patched sys.hexversion and a fake Tk."""
    monkeypatch.setattr(checkpyver.sys, 'hexversion', 0x03040000)
    monkeypatch.setattr(checkpyver.sys, 'exit', lambda status: None)

    try:
        import tkinter  # pylint: disable=unused-import
    except ImportError:
        tk_mock = mocker.patch('qutebrowser.misc.checkpyver.Tk',
                               spec=['withdraw'], new_callable=mocker.Mock)
        msgbox_mock = mocker.patch('qutebrowser.misc.checkpyver.messagebox',
                                   spec=['showerror'])
    else:
        tk_mock = mocker.patch('qutebrowser.misc.checkpyver.Tk', autospec=True)
        msgbox_mock = mocker.patch('qutebrowser.misc.checkpyver.messagebox',
                                   autospec=True)

    checkpyver.check_python_version()
    stdout, stderr = capfd.readouterr()
    assert not stdout
    assert not stderr
    tk_mock.assert_called_with()
    tk_mock().withdraw.assert_called_with()
    msgbox_mock.showerror.assert_called_with("qutebrowser: Fatal error!",
                                             unittest.mock.ANY)
