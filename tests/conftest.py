import os
import sys
import asyncio
import inspect

# Ensure project root is on sys.path so `import app` works in tests
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def pytest_pyfunc_call(pyfuncitem):
    """Allow running async tests without pytest-asyncio.

    If the test function is a coroutine, run it in a fresh event loop.
    """
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        funcargs = pyfuncitem.funcargs
        sig = inspect.signature(testfunction)
        # Filter only the parameters that the test function expects
        allowed = {name: funcargs[name] for name in sig.parameters.keys() if name in funcargs}
        asyncio.run(testfunction(**allowed))
        return True
    return None
