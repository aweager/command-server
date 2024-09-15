# Functions in this file assume the following shell parameters are defined:
#   - stdin
#   - stdout
#   - stderr
#   - socket

zmodload zsh/zutil

function start-job() {
    local -a arg_json_list jq_args
    local value i
    i=0
    for value; do
        arg_json_list+=("\$arg$i")
        jq_args+=(
            --arg "arg$i" "$value"
        )
        i="$(($i + 1))"
    done

    local id="$(
        jq -nc \
            --arg cwd "$PWD" \
            --arg stdin "$stdin" \
            --arg stdout "$stdout" \
            --arg stderr "$stderr" \
            "$jq_args[@]" "{
                \"cwd\": \$cwd,
                \"args\": [ ${(j:,:)arg_json_list} ],
                \"stdio\": {
                    \"stdin\": \$stdin,
                    \"stdout\": \$stdout,
                    \"stderr\": \$stderr
                }
            }" \
                | jrpc-oneoff request "$socket" command_server.stop \
                | jq -rcj '.job.id' && echo x
    )"
    REPLY="${id%x}"
}

function signal-job() {
    local id="$1"
    local signal="$2"

    jq -nc --arg id "$id" --arg signal "$signal" '{
        "id": $id,
        "signal": $signal
    }' | jrpc-oneoff request "$socket" job.signal > /dev/null
}

function wait-for-job() {
    local id="$1"

    local exit_code="$(
        jq -nc --arg id "$id" '{
            "id": $id
        }' \
        | jrpc-oneoff request "$socket" job.wait \
        | jq -rcj '.exit_code'
    )"
    return "$exit_code"
}

function reload-executor() {
    local -a override_cwd
    local -a override_args
    zparseopts -D \
        -cwd:=override_cwd \
        -override-args=override_args

    local -a config_overrides jq_args

    if [[ -n $override_args ]]; then
        local -a arg_json_list
        local value i
        i=0
        for value; do
            arg_json_list+=("\$arg$i")
            jq_args+=(
                --arg "arg$i" "$value"
            )
            i="$(($i + 1))"
        done

        config_overrides+=("\"args\": [ ${(j:,:)arg_json_list} ]")
    fi

    if [[ -n $override_cwd ]]; then
        jq_args+=(
            --arg cwd "$override_cwd[-1]"
        )
        config_overrides+=("\"cwd\": \$cwd")
    fi

    jq_args+=(
        --arg stdin "$stdin"
        --arg stdout "$stdout"
        --arg stderr "$stderr"
    )

    local params='{
        "stdio": {
            "stdin": $stdin,
            "stdout": $stdout,
            "stderr": $stderr
        },
        "config_overrides": '
    params+="{ ${(j:,:)config_overrides} }}"

    local id="$(
        jq -nc "$jq_args[@]" "$params" \
            | jrpc-oneoff request "$socket" executor.reload \
            | jq -rcj '.executor.id' && echo x)"
    REPLY="${id%x}"
}

function cancel-reload() {
    local id="$1"
    local signal="$2"

    jq -nc --arg id "$id" --arg signal "$signal" '{
        "id": $id,
        "signal": $signal
    }' | jrpc-oneoff request "$socket" executor.cancel-reload > /dev/null
}

function wait-for-reload() {
    local id="$1"

    local exit_code="$(
        jq -nc --arg id "$id" '{
            "id": $id
        }' \
        | jrpc-oneoff request "$socket" executor.wait-ready \
        | jq -rcj '.executor.state.exit_code'
    )"

    if [[ "$exit_code" != null ]]; then
        return "$exit_code"
    fi
}

function stop-server() {
    echo '{}' | jrpc-oneoff request "$1" command_server.stop > /dev/null
}
