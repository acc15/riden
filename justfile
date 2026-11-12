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

# Собрать артефакты (перед сборкой прогоняет check)
build: check
    uv build --clear

# Поднять версию (patch по умолчанию): just bump, just bump minor --dry-run
bump part="patch" *args:
    uv run bump-my-version bump {{ part }} {{ args }}

# Опубликовать на PyPI (patch по умолчанию): just publish, just publish minor --dry-run
publish part="patch" *args: (bump part args) build
    UV_PUBLISH_TOKEN="${PYPI_TOKEN:-}" uv publish --publish-url {{ pypi_url }} {{ args }}

# Опубликовать текущую версию на TestPyPI (без bump и тэга)
publish-test *args: build
    UV_PUBLISH_TOKEN="${TEST_PYPI_TOKEN:-}" uv publish --publish-url {{ test_pypi_url }} {{ args }}
