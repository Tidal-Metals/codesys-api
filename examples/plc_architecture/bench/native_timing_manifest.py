"""Native serial manifest for timing tests: every server reads N registers, no I/O mappings, the ME31 parked.

Usage: python examples/plc_architecture/bench/native_timing_manifest.py <registers> <cycle_ms> [--park-cycle-ms 3600000]
Writes tmp/arch_bench/native_timing_<registers>.json from the generated native_serial.json, for
modbus_device_driver_runner.py --skip-simulator. Mappings are left out (each costs ~10 s of I/O round trips and a
rate test reads the simulator's counters, not the values). The real ME31 (unit 1) keeps its 6-register channel
with an hour-long cycle: it must exist (PRG_NativeSerial refers to it) but only answers at 9600 baud.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ME31_UNIT = 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("registers", type=int)
    parser.add_argument("cycle_ms", type=int)
    parser.add_argument("--park-cycle-ms", type=int, default=3600000)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "tmp" / "arch_bench" / "src" / "native_serial.json").read_text(encoding="utf-8"))
    for device in manifest["devices"]:
        device.pop("mappings", None)
        for channel in device["channels"]:
            if device["unit"] == ME31_UNIT:
                channel["cycleTime"] = args.park_cycle_ms
            else:
                channel["readLength"] = args.registers
                channel["cycleTime"] = args.cycle_ms
    out = ROOT / "tmp" / "arch_bench" / ("native_timing_%d.json" % args.registers)
    out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
