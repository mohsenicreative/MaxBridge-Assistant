import argparse
import hashlib
from pathlib import Path


def sha256_file(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    Compute SHA-256 hash for ANY file type.
    Cross-platform, Unicode-safe, works with long Windows paths.
    """

    file_path = Path(file_path)

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found or not a file: {file_path}")

    h = hashlib.sha256()

    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)

    return h.hexdigest()


def verify_file(file_path: Path, expected_hash: str) -> bool:
    """
    Verify file integrity against expected SHA-256 hash.
    """

    actual_hash = sha256_file(file_path)
    return actual_hash.lower() == expected_hash.lower()


def main():
    parser = argparse.ArgumentParser(description="Universal SHA-256 file hashing tool")

    parser.add_argument(
        "file", type=str, help="Path to any file (zip, exe, png, fbx, etc.)"
    )

    parser.add_argument("--verify", type=str, help="Expected SHA-256 hash (optional)")

    args = parser.parse_args()

    file_path = Path(args.file)

    try:
        file_hash = sha256_file(file_path)
        print(f"\nFile: {file_path}")
        print(f"SHA-256: {file_hash}")

        if args.verify:
            if verify_file(file_path, args.verify):
                print("✔ Verification: VALID")
            else:
                print("❌ Verification: FAILED")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
