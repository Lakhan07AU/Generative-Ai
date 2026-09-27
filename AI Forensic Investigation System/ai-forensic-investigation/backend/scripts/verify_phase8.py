"""Phase verification entry point - see verify_final_system.py for the checks.

Run standalone:
    python scripts/verify_phase8.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verify_final_system import check_phase8  # noqa: E402


def main() -> int:
    print("\n" + "=" * 40)
    print("verify_phase8.py")
    print("=" * 40)
    status = check_phase8()
    print(f"\nRESULT: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())