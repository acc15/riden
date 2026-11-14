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
ruff *args:
    uv run ruff check . {{ args }}

# Тесты (аргументы пробрасываются: just test -k model)
test *args:
    uv run pytest {{ args }}

# Линт: ty + ruff
lint: ty ruff

# Полная проверка: lint + тесты
check: lint test

# Собрать артефакты (перед сборкой прогоняет check)
build: check
    uv build --clear

# Поднять версию: just bump patch, just bump minor --dry-run
bump *args:
    uv run bump-my-version bump {{ args }}

# Опубликовать на PyPI: just publish, just publish --dry-run
publish *args:
    UV_PUBLISH_TOKEN="${PYPI_TOKEN:-}" uv publish --publish-url {{ pypi_url }} {{ args }}

# Опубликовать на TestPyPI: just publish-test, just publish-test --dry-run
publish-test *args:
    UV_PUBLISH_TOKEN="${TEST_PYPI_TOKEN:-}" uv publish --publish-url {{ test_pypi_url }} {{ args }}
