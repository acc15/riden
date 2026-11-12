set dotenv-load

pypi_url := "https://upload.pypi.org/legacy/"
test_pypi_url := "https://test.pypi.org/legacy/"

# Показать список задач
default:
    @just --list

# Проверка типов
ty:
    uv run ty check

# Линтер
ruff:
    uv run ruff check .

# Тесты (аргументы пробрасываются: just test -k model)
test *args:
    uv run pytest {{ args }}

# Линт: ty + ruff
lint: ty ruff

# Полная проверка: lint + тесты
check: lint test

build: check
    uv build --clear

# Публикация на TestPyPI; аргументы пробрасываются: just publish-test --dry-run
publish-test *args: build
    @UV_PUBLISH_TOKEN="${TEST_PYPI_TOKEN:-}" uv publish --publish-url {{ test_pypi_url }} {{ args }}

# Публикация на PyPI; аргументы пробрасываются: just publish --dry-run
publish *args: build
    @UV_PUBLISH_TOKEN="${PYPI_TOKEN:-}" uv publish --publish-url {{ pypi_url }} {{ args }}
