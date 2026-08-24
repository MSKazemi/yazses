#!/bin/bash
cd ~/yazses || exit 1
while pgrep -f "queue_x86b.sh" | grep -qv $$; do sleep 60; done
echo "=== queue1 done $(date -u +%FT%TZ) ==="
# The existing test-other WER artifact predates the provenance chokepoint, so it is
# re-measured rather than hand-stamped.
.venv/bin/python paper/benchmark/bench_wer.py 200 full --split test-other
echo "=== wer-other rc=$? $(date -u +%FT%TZ) ==="
echo QUEUE_X86B2_DONE
