#!/bin/sh

set -eu

run_seed() {
    echo "Running database seed script..."
    python -m src.database.populate
    echo "Database seed script completed."
}

ALEMBIC_CONFIG="/usr/src/fastapi/alembic.ini"

echo "Applying committed database migrations..."
alembic -c "$ALEMBIC_CONFIG" upgrade head
echo "Database migrations applied successfully."

run_seed
