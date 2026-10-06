"""
Verification harness for the config dialog monitor-list labels
(config_logic.monitor_label / config_logic._mac_display_details).

mss 9 and mss 10 cannot coexist in one venv, so the mss 9 code path is
verified against stub monitor dicts shaped exactly like what mss 9 emits
(left/top/width/height only, on every platform - mss 9 never populated
name/is_primary either). The mss 10 path is verified live in a venv that
has mss 10 installed: run this harness there without --stub-only.

Usage:
    python3 tests/verify_monitor_labels.py               # stub checks + live label build
    python3 tests/verify_monitor_labels.py --stub-only   # stub checks only (no mss needed)

Proven by the stubs:
    a) mss 9-shaped dicts (no name/is_primary) render generic but
       distinguishable labels, same as mss 10's dict shape
    b) dicts that do supply name/is_primary render those, and the primary
       flag shows through
    c) the macOS system_profiler enrichment parses real display names and
       the main flag, and degrades to None off-macOS or on failure
"""
import os
import sys

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
os.chdir(SRC_DIR)
sys.path.insert(0, SRC_DIR)

import config_logic  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, condition: bool, extra: str = '') -> None:
    """ Assert a check, tallying pass/fail instead of aborting """
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f'  ok   {label}')
    else:
        FAIL += 1
        print(f'  FAIL {label} {extra}')


def verify_mss9_stubs() -> None:
    """ a)+b): label rendering over stub monitor dicts """
    print('mss 9-shaped dicts (left/top/width/height only):')
    # exactly what mss 9.0.x emits on macOS/Windows/Linux: no name, no is_primary
    mss9 = [
        {'left': 0, 'top': 0, 'width': 1920, 'height': 1080},
        {'left': 1920, 'top': 0, 'width': 1920, 'height': 1080},
    ]
    l1 = config_logic.monitor_label(0, mss9[0])
    l2 = config_logic.monitor_label(1, mss9[1])
    print(f'    {l1}')
    print(f'    {l2}')
    check('no crash without name/is_primary', True)
    check('same-size displays stay distinguishable', l1 != l2, f'({l1} == {l2})')
    check('keeps the width x height read', '1920x1080' in l1)
    check('origin fallback included', '(0, 0)' in l1 and '(1920, 0)' in l2)

    print('dicts that do supply name/is_primary (defensive path):')
    named = {'left': 0, 'top': 0, 'width': 3840, 'height': 2160, 'name': 'LG UltraFine', 'is_primary': True}
    l3 = config_logic.monitor_label(0, named)
    print(f'    {l3}')
    check('dict name wins', 'LG UltraFine' in l3)
    check('dict primary flag shows', '(primary)' in l3)

    print('details enrichment overrides only missing pieces:')
    details = [('LG UltraFine', True), (None, False)]
    l4 = config_logic.monitor_label(0, mss9[0], details)
    l5 = config_logic.monitor_label(1, mss9[1], details)
    l6 = config_logic.monitor_label(2, mss9[0], details)  # out of range: must not crash
    print(f'    {l4}')
    print(f'    {l5}')
    check('mac name applied to unnamed dict', 'LG UltraFine' in l4 and '(primary)' in l4)
    check('still generic where details have no name', 'unknown' in l5)
    check('out-of-range details ignored', 'unknown' in l6)


FAKE_PROFILER = """Graphics/Displays:

    Apple M3 Max:

      Chipset Model: Apple M3 Max
      Type: GPU
      Bus: Built-In
      Total Number of Cores: 40
      Displays:
        Color LCD:
          Resolution: 3456 x 2234 Retina
          Main Display: Yes
          Mirror: Off
          Online: Yes
          Connection Type: Internal
        UltraFine 32:
          Display Type: LG UltraFine 32
          Resolution: 3840 x 2160
          Main Display: No
          Mirror: Off
          Online: Yes
          Connection Type: Thunderbolt 3

    AMD Radeon Pro:

      Chipset Model: AMD Radeon Pro
      Type: GPU
      Bus: PCIe
      Displays:
        EDID:
          Resolution: 2560 x 1440
          Main Display: No
          Online: Yes
          Connection Type: HDMI
"""


class FakeRun:
    """ stands in for subprocess.run, returning the canned system_profiler text """

    stdout = FAKE_PROFILER

    def __init__(self, *args, **kwargs) -> None:
        pass


def verify_mac_details() -> None:
    """ c): the macOS system_profiler enrichment """
    print('macOS system_profiler enrichment:')
    import platform

    real_system = platform.system
    real_run = config_logic.subprocess.run
    config_logic.platform.system = lambda: 'Darwin'
    config_logic.subprocess.run = FakeRun
    try:
        details = config_logic._mac_display_details()
    finally:
        config_logic.platform.system = real_system
        config_logic.subprocess.run = real_run
    print(f'    {details}')
    check('three displays parsed', details is not None and len(details) == 3, f'(got {details})')
    check('entry header kept when no Display Type line', details[0] == ('Color LCD', True), f'(got {details[0]})')
    check('Display Type line wins over header', details[1] == ('LG UltraFine 32', False), f'(got {details[1]})')
    check('second GPU section stays separate', details[2] == ('EDID', False), f'(got {details[2]})')

    print('off-macOS and failure cases:')
    config_logic.platform.system = lambda: 'Windows'
    try:
        check('non-macOS returns None', config_logic._mac_display_details() is None)
    finally:
        config_logic.platform.system = real_system

    config_logic.platform.system = lambda: 'Darwin'

    class BoomRun:
        def __init__(self, *args, **kwargs) -> None:
            raise OSError('no system_profiler')

    config_logic.subprocess.run = BoomRun
    try:
        check('profiler failure returns None', config_logic._mac_display_details() is None)
    finally:
        config_logic.platform.system = real_system
        config_logic.subprocess.run = real_run


def verify_live() -> None:
    """ the mss path of the installed venv (mss 10 in the task venv, mss 9 in a 9.x venv) """
    print('live mss monitors through monitor_label:')
    import mss

    print(f'    mss {mss.__version__}')
    monitors = mss.MSS().monitors[1::]
    details = config_logic._mac_display_details()
    if details is not None and len(details) != len(monitors):
        details = None  # same guard config_page applies before labelling
    for idx, monitor in enumerate(monitors):
        label = config_logic.monitor_label(idx, monitor, details)
        print(f'    {label}')
        check(f'label {idx} non-empty', len(label) > 0)


def main() -> int:
    stub_only = '--stub-only' in sys.argv[1:]
    verify_mss9_stubs()
    verify_mac_details()
    if not stub_only:
        verify_live()
    print(f'\n{PASS} passed, {FAIL} failed')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
