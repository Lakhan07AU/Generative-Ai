"""Phase verification entry point - see verify_final_system.py for the checks.

Run standalone:
    python scripts/verify_phase7.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verify_final_system import check_phase7  # noqa: E402


def main() -> int:
    print("\n" + "=" * 40)
    print("verify_phase7.py")
    print("=" * 40)
    status = check_phase7()
    print(f"\nRESULT: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())