"""Build the M4-B/REAL-01 source review package with the established secret scan."""

from __future__ import annotations

import sys

import make_ui01_zip as package

package.ZIP_NAME = "m4b-real01-source.zip"
package.SENSITIVE_EXEMPT.update(
    {
        "tests/test_memory_system.py": "Synthetic SK-PLACEHOLDER validates memory rejection",
        "tests/test_custom_providers.py": "Synthetic TEST-TOKEN validates credential isolation",
    }
)


if __name__ == "__main__":
    sys.exit(package.main())
