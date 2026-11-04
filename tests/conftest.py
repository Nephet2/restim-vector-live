"""Keep cyclic Tcl interpreter finalization outside UI construction."""
import gc
import pytest

@pytest.fixture(autouse=True)
def collect_tcl_interpreters_between_tests():
    # A previous Tk root can be cyclic garbage after destroy(). Collecting it
    # during initialization of another interpreter corrupts Tcl library loading.
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        gc.collect()
        if was_enabled:
            gc.enable()
