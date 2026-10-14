"""Load the sample vault. Pass reset to wipe the collection first."""

import sys

from app.orchestrator import Vault
from app.samples import seed_vault


def main() -> None:
    reset = len(sys.argv) > 1 and sys.argv[1] == "reset"
    vault = Vault()
    try:
        added = seed_vault(vault, reset=reset)
    finally:
        vault.close()
    print(f"Seeded {added} notes")


if __name__ == "__main__":
    main()
