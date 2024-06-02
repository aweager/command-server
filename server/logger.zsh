autoload -Uz colors && colors

typeset -gx INDENT
typeset -gAH LogLevels
LogLevels=(
    trace 0
    debug 1
    info 2
    warn 3
    error 4
    fatal 5
    disabled 6
)

if [[ ! -v LOG_FD ]]; then
    typeset -gxH LOG_FD
    exec {LOG_FD}>> "${LOG-/dev/null}"
fi

if [[ ! -v STDOUT_FD ]]; then
    typeset -gxH STDOUT_FD
    exec {STDOUT_FD}>&1
fi

if [[ ! -v STDERR_FD ]]; then
    typeset -gxH STDERR_FD
    exec {STDERR_FD}>&2
fi

function log() {
    echo "$*" >&$LOG_FD
}

function stdout() {
    echo "$*" >&$STDOUT_FD
}

function stderr() {
    echo "$*" >&$STDERR_FD
}

function log.trace() {
    echo "$*" | .log-at-level \
        trace \
        "TRACE: " \
        '\e[38;5;8m' \
        "$STDOUT_FD"
}

function log.debug() {
    echo "$*" | .log-at-level \
        debug \
        "DEBUG: " \
        "$fg[cyan]" \
        "$STDOUT_FD"
}

function log.info() {
    echo "$*" | .log-at-level \
        info \
        "INFO : " \
        "" \
        "$STDOUT_FD"
}

function log.warn() {
    echo "$*" | .log-at-level \
        warn \
        "WARN : " \
        "$fg[yellow]" \
        "$STDOUT_FD"
}

function log.error() {
    echo "$*" | .log-at-level \
        error \
        "ERROR: " \
        '\e[38;5;9m' \
        "$STDERR_FD"
}

function log.fatal() {
    echo "$*" | .log-at-level \
        fatal \
        "FATAL: " \
        "$fg[red]" \
        "$STDERR_FD"
}

function .log-at-level() {
    local level="$1"
    local prefix="$2"
    local color="$3"
    local std_fd="$4"

    if [[ "$LogLevels[${LOG_LEVEL-info}]" -gt "$LogLevels[$level]" ]]; then
        return
    fi

    local line=""
    while IFS=\n read -t line; do
        echo "${color}${prefix}${INDENT}${line}${reset_color}" >&$std_fd
        echo "${prefix}${INDENT}${line}" >&$LOG_FD
    done
}
