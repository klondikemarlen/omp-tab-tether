.PHONY: lint test

lint:
	ruff check --no-cache install.py host tests
	biome lint --error-on-warnings --only=correctness --only=suspicious extension tests

test:
	PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
	node --test tests/*.test.*
