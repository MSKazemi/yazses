set -x
export PATH="$HOME/.local/bin:$PATH"
export QT_QPA_PLATFORM=offscreen
cd ~/yazses
uv run pytest tests/ -v > ~/x86_extras_pytest.log 2>&1
echo "PYTEST_EXIT=$?" | tee -a ~/x86_extras_pytest.log
echo "=== the three tests the CI comment names as never-run ==="
uv run pytest tests/test_shipped_backends.py tests/test_meeting_notes.py -v \
  > ~/x86_three.log 2>&1
echo "THREE_EXIT=$?" | tee -a ~/x86_three.log
