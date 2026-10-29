#!/bin/sh
# Runs once, on the first start of an empty MySQL data volume.
# Creates the application database, the test database, and the two users.
# You do not run this by hand. Compose mounts it into the MySQL image.
set -eu

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}_test\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
CREATE USER IF NOT EXISTS '${DB_MIGRATION_USER}'@'%' IDENTIFIED BY '${DB_MIGRATION_PASSWORD}';

GRANT SELECT, INSERT, UPDATE, DELETE ON \`${DB_NAME}\`.* TO '${DB_USER}'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`${DB_NAME}_test\`.* TO '${DB_USER}'@'%';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_MIGRATION_USER}'@'%';
GRANT ALL PRIVILEGES ON \`${DB_NAME}_test\`.* TO '${DB_MIGRATION_USER}'@'%';
FLUSH PRIVILEGES;
SQL
