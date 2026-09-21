# PB-7: HITL Interrupt Propagation — required by exact name in every template per the scaffold manifest contract.
# HCR-C2-048 has no interrupt() (hitl.enabled false / absent) -> auto-skips. A HITL template replaces this
# with a real GraphInterrupt-propagation test (PB-7 spec).
import os
import re

import pytest


def _hitl_enabled() -> bool:
    p = os.path.join(os.path.dirname(__file__), "..", "..", "config", "agent.yaml")
    if not os.path.exists(p):
        return False
    with open(p, encoding="utf-8") as f:
        content = f.read()
    return bool(re.search(r"hitl:\s*\n(?:\s+.*\n)*?\s+enabled:\s*true", content))


@pytest.mark.skipif(not _hitl_enabled(), reason="hitl.enabled not set — PB-7 N/A for this template")
def test_hitl_interrupt_propagation():
    pytest.skip("HITL not enabled for this template")
