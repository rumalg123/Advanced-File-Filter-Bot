#!/usr/bin/env bash
# Exercise committed Redis configs from distinct containers without host ports.
set -euo pipefail

qa_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
qa_tmp=$(mktemp -d)
qa_prefix="affb-redis-qa-$$-${RANDOM}"
qa_network="${qa_prefix}-network"
qa_names=()
qa_network_created=false

qa_cleanup() {
    if ((${#qa_names[@]})); then
        sudo docker rm -f -v "${qa_names[@]}" >/dev/null 2>&1 || true
    fi
    if [[ "$qa_network_created" == true ]]; then
        sudo docker network rm "$qa_network" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$qa_tmp"
}
trap qa_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

sudo docker network create --internal "$qa_network" >/dev/null
qa_network_created=true
for qa_role in cache state; do
    qa_config=redis.conf
    [[ "$qa_role" != state ]] || qa_config=redis-state.conf
    cp -- "$qa_root/$qa_config" "$qa_tmp/$qa_config"
    # Official Redis drops to its service user. These configs contain no secrets;
    # the checkout may have private permissions that block that user.
    chmod 0644 "$qa_tmp/$qa_config"
    qa_server="${qa_prefix}-${qa_role}"
    qa_names+=("$qa_server")
    sudo docker run -d --name "$qa_server" --network "$qa_network" \
        --network-alias "$qa_role" --memory 384m --cpus 1 \
        -v "$qa_tmp/$qa_config:/qa.conf:ro" \
        redis:7-alpine redis-server /qa.conf >/dev/null

    qa_ready=false
    for qa_attempt in {1..30}; do
        if [[ $(sudo docker exec "$qa_server" redis-cli PING 2>/dev/null) == PONG ]]; then
            qa_ready=true
            break
        fi
        sleep 0.2
    done
    if [[ "$qa_ready" != true ]]; then
        sudo docker logs --tail 10 "$qa_server"
        exit 1
    fi

    qa_probe="${qa_prefix}-${qa_role}-probe"
    qa_names+=("$qa_probe")
    qa_response=$(timeout 15s sudo docker run --rm --name "$qa_probe" \
        --network "$qa_network" redis:7-alpine \
        sh -c 'timeout 5 redis-cli -h "$1" PING' sh "$qa_role")
    # redis-cli can exit zero even when protected mode returns DENIED.
    if [[ "$qa_response" != PONG ]]; then
        printf '%s Redis rejected the separate-container probe\n' "$qa_role" >&2
        exit 1
    fi
    printf '%s Redis separate-container connectivity passed\n' "$qa_role"
done
