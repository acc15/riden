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

# Поднять patch-версию: тесты, lock, сборка, коммит, тэг
bump *args: (_bump "patch" args)

# Поднять minor-версию
bump-minor *args: (_bump "minor" args)

# Поднять major-версию
bump-major *args: (_bump "major" args)

# Опубликовать patch-релиз на PyPI
publish *args: (_bump "patch" args) build (_upload args)

# Опубликовать minor-релиз на PyPI
publish-minor *args: (_bump "minor" args) build (_upload args)

# Опубликовать major-релиз на PyPI
publish-major *args: (_bump "major" args) build (_upload args)

# Опубликовать текущую версию на TestPyPI (без bump и тэга)
publish-test *args: build
    UV_PUBLISH_TOKEN="${TEST_PYPI_TOKEN:-}" uv publish --publish-url {{ test_pypi_url }} {{ args }}

[private]
_bump part *args:
    uv run bump-my-version bump {{ part }} {{ args }}

[private]
_upload *args:
    UV_PUBLISH_TOKEN="${PYPI_TOKEN:-}" uv publish --publish-url {{ pypi_url }} {{ args }}
