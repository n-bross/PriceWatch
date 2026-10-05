"""Resume fresh bounded ROSSMANN imports using the recurring checkpoint.

Replaces the legacy CDP attachment and replay of undated audit captures.
Accepts the same --state, --max-pages and --browser arguments as sync_rossmann.py.
"""

from pricewatch_api.rossmann_recurring import main

if __name__ == "__main__":
    main()
