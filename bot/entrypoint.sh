#!/bin/sh
set -e
chown -R appuser:appuser /app/data
exec gosu appuser python -m bot.main
