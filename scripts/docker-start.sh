#!/bin/bash
set -e

# Start dbus daemon
echo "Starting dbus..."
mkdir -p /run/dbus
dbus-daemon --system --nofork --nopidfile --nosyslog &
DBUS_PID=$!
sleep 1

# Verify dbus is running
if ! kill -0 $DBUS_PID 2>/dev/null; then
    echo "ERROR: dbus failed to start"
    exit 1
fi

# Start firewalld
echo "Starting firewalld..."
firewalld --nofork --nopid &
FIREWALLD_PID=$!
sleep 2

# Verify firewalld is running
if ! kill -0 $FIREWALLD_PID 2>/dev/null; then
    echo "ERROR: firewalld failed to start"
    exit 1
fi

echo "firewalld is running"

# If arguments are provided, execute them
if [ $# -gt 0 ]; then
    exec "$@"
else
    # Keep container running and tail firewalld log
    echo "Container ready. Use 'docker exec' to run commands."
    tail -f /var/log/firewalld 2>/dev/null || tail -f /dev/null
fi
