"""Build the M5-B source-only review package and reject secrets or screenshots."""

from __future__ import annotations

import sys

import make_ui01_zip as package

package.ZIP_NAME = "m5b-source.zip"
package.EXCLUDE_DIRS.add("shots")
package.NAME_EXCLUDES.update(
    {
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.gif",
        "*.webp",
        "*.bmp",
        "*.tiff",
        "*.raw",
    }
)
package.SENSITIVE_EXEMPT.update(
    {
        "tests/test_memory_system.py": "Synthetic placeholder validates memory rejection",
        "tests/test_custom_providers.py": "Synthetic token validates credential isolation",
    }
)


if __name__ == "__main__":
    sys.exit(package.main())
