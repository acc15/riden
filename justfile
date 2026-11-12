set dotenv-load
set positional-arguments

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

# Поднять версию, прогнать тесты, собрать, закоммитить и поставить тэг
bump *args:
    #!/usr/bin/env bash
    set -euo pipefail
    part=patch
    case "${1:-}" in
        major|minor|patch) part="$1"; shift ;;
    esac
    uv run bump-my-version bump "$part" "$@"

# Опубликовать на PyPI: bump версии, сборка и загрузка
publish *args:
    #!/usr/bin/env bash
    set -euo pipefail
    part=patch
    case "${1:-}" in
        major|minor|patch) part="$1"; shift ;;
    esac
    dry_run=0
    for arg in "$@"; do
        if [ "$arg" = "--dry-run" ]; then dry_run=1; fi
    done
    if [ "$dry_run" -eq 0 ]; then
        uv run bump-my-version bump "$part"
    else
        echo "dry run: version bump and tag skipped"
        just build
    fi
    UV_PUBLISH_TOKEN="${PYPI_TOKEN:-}" uv publish --publish-url {{ pypi_url }} "$@"

# Опубликовать текущую версию на TestPyPI (без bump и тэга)
publish-test *args:
    #!/usr/bin/env bash
    set -euo pipefail
    just build
    UV_PUBLISH_TOKEN="${TEST_PYPI_TOKEN:-}" uv publish --publish-url {{ test_pypi_url }} "$@"
