import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from signal_transcriber.backends import _convert_to_m4a


def test_convert_to_m4a_uses_overwrite_flag():
    with patch("signal_transcriber.backends.subprocess.run") as mock_run, \
         patch("signal_transcriber.backends.make_temp_path", return_value=Path("/tmp/out.m4a")):
        mock_run.return_value = MagicMock(returncode=0)
        _convert_to_m4a(Path("/tmp/input.aac"))

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd


def test_convert_to_m4a_cleans_up_on_failure():
    """_convert_to_m4a removes the temp file when ffmpeg fails."""
    mock_path = MagicMock(spec=Path)
    with patch("signal_transcriber.backends.make_temp_path", return_value=mock_path), \
         patch("signal_transcriber.backends.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "ffmpeg")), \
         pytest.raises(subprocess.CalledProcessError):
        _convert_to_m4a(Path("/tmp/input.aac"))

    mock_path.unlink.assert_called_once_with(missing_ok=True)
