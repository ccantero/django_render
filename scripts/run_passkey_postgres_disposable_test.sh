#!/usr/bin/env bash
# Run the Passkey PostgreSQL validation suite against an isolated Docker target.
# This script intentionally creates and removes only resources named from its
# own UUID token.  It never reads .env files or prints database credentials.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
resource_token="$(tr -d '-' </proc/sys/kernel/random/uuid)"
container_name="django-render-passkey-pg-${resource_token}"
volume_name="django-render-passkey-pg-data-${resource_token}"
database_name="test_passkey_validation_${resource_token:0:12}"
template_name="template_passkey_${resource_token:0:12}"
django_test_database_name="test_django_passkey_${resource_token:0:12}"
database_user="passkey_test"
host_port=""
temp_dir=""
validation_failed=0
declare -A stage_status=(
    [database_initialization]=NOT_RUN
    [migrations]=NOT_RUN
    [migration_consistency]=NOT_RUN
    [security_checks]=NOT_RUN
    [postgres_concurrency]=NOT_RUN
    [full_django_suite]=NOT_RUN
    [django_test_database_cleanup]=NOT_RUN
)

report_stages() {
    local stage
    for stage in database_initialization migrations migration_consistency security_checks \
        postgres_concurrency full_django_suite django_test_database_cleanup; do
        printf 'VALIDATION_STAGE_%s = %s\n' "${stage}" "${stage_status[${stage}]}"
    done
}

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

cleanup() {
    local exit_code=$?
    local cleanup_failed=0
    local resource_label
    set +e

    resource_label="$(docker container inspect --format '{{ index .Config.Labels "com.django-render.passkey-harness" }}' "${container_name}" 2>/dev/null || true)"
    if [[ -n "${resource_label}" ]]; then
        if [[ "${resource_label}" != "${resource_token}" ]]; then
            printf '%s\n' 'refusing to remove a container not owned by this harness run' >&2
            cleanup_failed=1
        else
            docker rm -f "${container_name}" >/dev/null 2>&1 || cleanup_failed=1
            docker container inspect "${container_name}" >/dev/null 2>&1 && cleanup_failed=1
        fi
    fi

    resource_label="$(docker volume inspect --format '{{ index .Labels "com.django-render.passkey-harness" }}' "${volume_name}" 2>/dev/null || true)"
    if [[ -n "${resource_label}" ]]; then
        if [[ "${resource_label}" != "${resource_token}" ]]; then
            printf '%s\n' 'refusing to remove a volume not owned by this harness run' >&2
            cleanup_failed=1
        else
            docker volume rm "${volume_name}" >/dev/null 2>&1 || cleanup_failed=1
            docker volume inspect "${volume_name}" >/dev/null 2>&1 && cleanup_failed=1
        fi
    fi
    if [[ -n "${temp_dir}" && -d "${temp_dir}" ]]; then
        rm -rf -- "${temp_dir}" || cleanup_failed=1
    fi

    report_stages
    if [[ "${validation_failed}" != 0 || "${exit_code}" != 0 ]]; then
        printf '%s\n' 'VALIDATION_OVERALL = FAIL' >&2
        exit_code=1
    else
        printf '%s\n' 'VALIDATION_OVERALL = PASS'
    fi

    if [[ "${cleanup_failed}" == 0 ]]; then
        printf '%s\n' 'DISPOSABLE_RESOURCE_CLEANUP_VERIFIED = YES'
    else
        printf '%s\n' 'DISPOSABLE_RESOURCE_CLEANUP_VERIFIED = NO' >&2
        [[ "${exit_code}" == 0 ]] && exit_code=1
    fi
    exit "${exit_code}"
}
trap cleanup EXIT

command -v docker >/dev/null || fail 'docker is required on the authorized development host'
command -v openssl >/dev/null || fail 'openssl is required to generate non-printed disposable credentials'
python_bin="${PYTHON_BIN:-${repo_root}/.venv/bin/python}"
[[ "${python_bin}" = /* ]] || fail 'PYTHON_BIN must be an absolute path'
[[ -x "${python_bin}" ]] || fail "expected executable Python at ${python_bin}"

# The harness deliberately refuses any caller-provided database target.
for forbidden_name in DATABASE_URL SUPABASE_DATABASE_URL PASSKEY_TEST_DATABASE_URL; do
    [[ -z "${!forbidden_name:-}" ]] || fail "${forbidden_name} must be unset before running this harness"
done

bootstrap_password="$(openssl rand -hex 32)"
test_password="$(openssl rand -hex 32)"
# This deliberately synthetic key meets Django's deployment-check requirements.
# It is neither read from the environment nor suitable for any non-disposable use.
synthetic_secret_key='r9!Qv4Mz7kL2xN8cH5wT1pA6dS3fG0jB9uE4yI7oR2lV5nC8hK1mX6qZ'
temp_dir="$(mktemp -d /tmp/django-render-passkey-pg.XXXXXX)"

psql_bootstrap() {
    docker exec -e PGPASSWORD="${bootstrap_password}" "${container_name}" \
        psql --no-psqlrc --set ON_ERROR_STOP=1 --host 127.0.0.1 --port 5432 \
        --username postgres --dbname postgres "$@"
}

psql_test_role() {
    docker exec -e PGPASSWORD="${test_password}" "${container_name}" \
        psql --no-psqlrc --set ON_ERROR_STOP=1 --host 127.0.0.1 --port 5432 \
        --username "${database_user}" "$@"
}

initialize_database() {
    docker volume create --label "com.django-render.passkey-harness=${resource_token}" "${volume_name}" >/dev/null || return 1
    docker run --detach --name "${container_name}" \
        --label "com.django-render.passkey-harness=${resource_token}" \
        --volume "${volume_name}:/var/lib/postgresql/data" \
        --publish '127.0.0.1::5432' \
        --env POSTGRES_DB=postgres \
        --env POSTGRES_USER=postgres \
        --env POSTGRES_PASSWORD="${bootstrap_password}" \
        --health-cmd='pg_isready -U postgres -d postgres' \
        --health-interval=1s --health-timeout=2s --health-retries=60 \
        postgres:16 >/dev/null || return 1

    host_port="$(docker port "${container_name}" 5432/tcp | sed -n 's#^127\.0\.0\.1:\([0-9][0-9]*\)$#\1#p' | head -n 1)" || return 1
    [[ -n "${host_port}" ]] || return 1

    for attempt in $(seq 1 60); do
        health="$(docker inspect --format '{{.State.Health.Status}}' "${container_name}" 2>/dev/null || true)"
        [[ "${health}" == healthy ]] && break
        [[ "${health}" != unhealthy && "${attempt}" != 60 ]] || return 1
        sleep 1
    done

    # PostgreSQL bootstrap is confined to the new container. Every psql call uses
    # explicit TCP/password authentication. The test role is not a superuser;
    # CREATEDB is the minimum Django needs for its disposable test-database lifecycle.
    psql_bootstrap --command "CREATE ROLE ${database_user} LOGIN CREATEDB PASSWORD '${test_password}';" >/dev/null || return 1
    psql_bootstrap --command "CREATE DATABASE ${database_name} OWNER ${database_user};" >/dev/null || return 1
    # This is an ordinary disposable database. Django's test role owns it and can
    # therefore clone it through DATABASES['default']['TEST']['TEMPLATE'] without
    # granting template privileges to any other role.
    psql_bootstrap --command "CREATE DATABASE ${template_name} OWNER ${database_user};" >/dev/null || return 1
    for schema_database in "${database_name}" "${template_name}"; do
        psql_test_role --dbname "${schema_database}" \
            --command 'CREATE SCHEMA django AUTHORIZATION passkey_test;' >/dev/null || return 1
    done
    # Django creates each test database from template_name. The bot schema is
    # test-only infrastructure: it lets the session fixture create its
    # bot.dust_signal_reviews test table without touching the base database or
    # any external bot schema.
    psql_test_role --dbname "${template_name}" \
        --command 'CREATE SCHEMA bot AUTHORIZATION passkey_test;' >/dev/null || return 1
}

run_nonterminal_stage() {
    local stage_name="$1"
    shift

    if "$@"; then
        stage_status["${stage_name}"]=PASS
        printf 'VALIDATION_STAGE_%s = PASS\n' "${stage_name}"
    else
        stage_status["${stage_name}"]=FAIL
        validation_failed=1
        printf 'VALIDATION_STAGE_%s = FAIL\n' "${stage_name}" >&2
    fi
}

run_migration_consistency_check() {
    local check_output="${temp_dir}/makemigrations-check.log"

    if run_django manage.py makemigrations --check --dry-run >"${check_output}" 2>&1; then
        cat "${check_output}"
        stage_status[migration_consistency]=PASS
        printf '%s\n' 'MIGRATION_CONSISTENCY = PASS'
        return 0
    fi

    cat "${check_output}" >&2
    stage_status[migration_consistency]=FAIL
    validation_failed=1
    printf '%s\n' 'VALIDATION_STAGE_migration_consistency = FAIL' >&2
    if grep --fixed-strings --quiet \
        'core/migrations/0005_manualcorrection_alter_dustsignalreview_options.py' \
        "${check_output}"; then
        printf '%s\n' 'MIGRATION_CONSISTENCY = PRE_EXISTING_ORIGIN_MAIN_DRIFT' >&2
    else
        printf '%s\n' 'MIGRATION_CONSISTENCY = FAIL_UNCLASSIFIED' >&2
    fi
    return 0
}

assert_junit_tests_passed() {
    local junit_file="$1"
    local expected_tests="$2"
    local validation_label="$3"

    run_django -c '
import sys
import xml.etree.ElementTree as etree

root = etree.parse(sys.argv[1]).getroot()
if root.tag not in {"testsuite", "testsuites"}:
    raise SystemExit(f"Unexpected JUnit root element: {root.tag}")

cases = root.findall(".//testcase")
tests = len(cases)
skipped = sum(case.find("skipped") is not None for case in cases)
failures = sum(case.find("failure") is not None for case in cases)
errors = sum(case.find("error") is not None for case in cases)
expected_tests = int(sys.argv[2])
if (tests, skipped, failures, errors) != (expected_tests, 0, 0, 0):
    raise SystemExit(
        f"PostgreSQL concurrency validation invalid: tests={tests}, "
        f"skipped={skipped}, failures={failures}, errors={errors}"
    )
' "${junit_file}" "${expected_tests}" || return 1
    printf 'POSTGRES_CONCURRENCY_%s_CONFIRMED = %s passed, 0 skipped\n' \
        "${validation_label}" "${expected_tests}"
}

run_postgres_concurrency_stage() {
    local all_tests='tests/test_passkey_postgres_concurrency.py'
    local test_case
    local test_index=0
    local individual_junit
    local combined_junit="${temp_dir}/passkey-postgres-concurrency-combined.xml"
    local repeat_junit="${temp_dir}/passkey-postgres-concurrency-repeat.xml"
    local -a concurrency_tests=(
        'tests/test_passkey_postgres_concurrency.py::PasskeyPostgreSQLConcurrencyTests::test_only_one_simultaneous_consumer_can_consume_enrollment_proofs'
        'tests/test_passkey_postgres_concurrency.py::PasskeyPostgreSQLConcurrencyTests::test_only_one_simultaneous_consumer_can_consume_step_up_challenge'
        'tests/test_passkey_postgres_concurrency.py::PasskeyPostgreSQLConcurrencyTests::test_concurrent_rate_limit_requests_do_not_lose_attempts'
    )

    # Override the repository's speed-oriented pytest defaults: this validation
    # must exercise migrations and must not reuse any database between runs.
    for test_case in "${concurrency_tests[@]}"; do
        test_index=$((test_index + 1))
        individual_junit="${temp_dir}/passkey-postgres-concurrency-individual-${test_index}.xml"
        run_django -m pytest -q -rs -o addopts='' --junitxml="${individual_junit}" \
            "${test_case}" || return 1
        assert_junit_tests_passed "${individual_junit}" 1 "INDIVIDUAL_${test_index}" || return 1
    done

    run_django -m pytest -q -rs -o addopts='' --junitxml="${combined_junit}" \
        "${all_tests}" || return 1
    assert_junit_tests_passed "${combined_junit}" 3 COMBINED || return 1

    run_django -m pytest -q -rs -o addopts='' --junitxml="${repeat_junit}" \
        "${all_tests}" || return 1
    assert_junit_tests_passed "${repeat_junit}" 3 REPEAT || return 1
}

verify_django_test_database_cleanup() {
    if psql_bootstrap --tuples-only --no-align \
        --command "SELECT 1 FROM pg_database WHERE datname = '${django_test_database_name}';" | grep -qx '1'; then
        return 1
    fi
    printf '%s\n' 'DJANGO_TEST_DATABASE_CLEANUP_VERIFIED = YES'
}

# PostgreSQL bootstrap is confined to the new container. Every psql call uses
# explicit TCP/password authentication. The test role is not a superuser;
# CREATEDB is the minimum Django needs for its disposable test-database lifecycle.
if ! initialize_database; then
    stage_status[database_initialization]=FAIL
    fail 'disposable PostgreSQL database initialization failed; no validation stages will run'
fi
stage_status[database_initialization]=PASS
printf '%s\n' 'VALIDATION_STAGE_database_initialization = PASS'

test_url="postgresql://${database_user}:${test_password}@127.0.0.1:${host_port}/${database_name}"
run_django_test() {
    env -i \
        PATH="${PATH}" \
        PYTHONPATH="${repo_root}" \
        DJANGO_SKIP_ENV_FILE=1 \
        DJANGO_SETTINGS_MODULE=django_render.postgres_test_settings \
        PASSKEY_TEST_DATABASE_URL="${test_url}" \
        PASSKEY_TEST_TEMPLATE="${template_name}" \
        PASSKEY_TEST_DJANGO_DATABASE="${django_test_database_name}" \
        PASSKEY_TEST_HOST=passkeys.test \
        DATABASE_URL="${test_url}" \
        CC_DEBUG=True \
        SECRET_KEY="${synthetic_secret_key}" \
        TUTORIAL_BOT_TOKEN=passkey-disposable-token \
        TELEGRAM_WEBHOOK_TOKEN=passkey-disposable-webhook-token \
        PASSKEYS_ENABLED=True \
        "${python_bin}" "$@"
}

run_django_security_check() {
    env -i \
        PATH="${PATH}" \
        PYTHONPATH="${repo_root}" \
        DJANGO_SKIP_ENV_FILE=1 \
        DJANGO_SETTINGS_MODULE=django_render.postgres_test_settings \
        PASSKEY_TEST_DATABASE_URL="${test_url}" \
        PASSKEY_TEST_TEMPLATE="${template_name}" \
        PASSKEY_TEST_DJANGO_DATABASE="${django_test_database_name}" \
        PASSKEY_TEST_HOST=passkeys.test \
        PASSKEY_TEST_FORCE_PASSKEY_ORIGIN=1 \
        DATABASE_URL="${test_url}" \
        CC_DEBUG=False \
        SECRET_KEY="${synthetic_secret_key}" \
        TUTORIAL_BOT_TOKEN=passkey-disposable-token \
        TELEGRAM_WEBHOOK_TOKEN=passkey-disposable-webhook-token \
        PASSKEYS_ENABLED=True \
        PASSKEY_RP_ID=passkeys.test \
        PASSKEY_ALLOWED_ORIGINS=https://passkeys.test \
        "${python_bin}" "$@"
}

run_django() {
    run_django_test "$@"
}

printf '%s\n' 'POSTGRES_DISPOSABLE_TEST_EXECUTED = YES'
printf '%s\n' 'POSTGRES_TARGET_CONFIRMED_NON_PRODUCTION = YES'
psql_bootstrap --tuples-only --no-align --command 'SHOW server_version;' | sed 's/^/POSTGRES_VERSION = /'

cd "${repo_root}"
if ! run_django manage.py migrate --noinput; then
    stage_status[migrations]=FAIL
    fail 'fresh PostgreSQL migrations failed; no independent validation stages will run'
fi
stage_status[migrations]=PASS
printf '%s\n' 'VALIDATION_STAGE_migrations = PASS'

run_migration_consistency_check
run_nonterminal_stage security_checks run_django_security_check manage.py check --deploy --fail-level WARNING
run_nonterminal_stage postgres_concurrency run_postgres_concurrency_stage
run_nonterminal_stage full_django_suite run_django -m pytest -q -rs -o addopts=''
run_nonterminal_stage django_test_database_cleanup verify_django_test_database_cleanup

if [[ "${validation_failed}" != 0 ]]; then
    exit 1
fi
