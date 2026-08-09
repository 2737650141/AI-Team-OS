"""Build the M4-A review source package using the established UI package policy."""

from __future__ import annotations

import sys

import make_ui01_zip as package

package.ZIP_NAME = "m4a-source.zip"
package.SENSITIVE_EXEMPT.update(
    {
        "tests/test_memory_system.py": "Synthetic SK-PLACEHOLDER validates memory rejection",
        "tests/test_custom_providers.py": "Synthetic TEST-TOKEN validates credential isolation",
    }
)


if __name__ == "__main__":
    sys.exit(package.main())
