.PHONY: lint test

lint:
	ruff check --no-fix --no-cache install.py host tests
	oxlint --deny-warnings extension tests

test:
	PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
	node --test tests/*.test.*
