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
    uv run pytest {{args}}

# Линт: ty + ruff
lint: ty ruff

# Полная проверка: lint + тесты
check: lint test

build: check 
    uv build