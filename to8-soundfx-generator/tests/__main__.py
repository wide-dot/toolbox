"""Lance toute la suite : python3 -m tests"""
import importlib
import sys

failures = 0
for mod in ("tests.test_opll", "tests.test_analyze", "tests.test_rhythm",
            "tests.test_codegen_noise", "tests.test_design",
            "tests.test_melody"):
    print(f"--- {mod} ---")
    m = importlib.import_module(mod)
    for name in sorted(dir(m)):
        if not name.startswith("test_"):
            continue
        fn = getattr(m, name)
        if not callable(fn):
            continue
        try:
            fn()
            print(f"OK   {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {name}\n  {e}")
sys.exit(1 if failures else 0)
