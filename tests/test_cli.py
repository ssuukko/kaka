import os
import subprocess
import sys


def test_redirected_windows_codepage_still_emits_utf8():
    result = subprocess.run(
        [sys.executable, "-m", "kaka", "--demo", "--doctor"],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "연동 엔진 응답: 정상" in result.stdout.decode("utf-8")
    assert "실제 카카오톡에 접근하지 않습니다" in result.stdout.decode("utf-8")
