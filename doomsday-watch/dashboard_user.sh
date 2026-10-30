#!/bin/sh
# Add or reset a dashboard login (asks for the password, hidden):
#   sudo sh dashboard_user.sh NAME
# Remove a login:
#   sudo sh dashboard_user.sh NAME remove
set -eu
name="${1:-}"
case "$name" in
	"" | *[!A-Za-z0-9_.-]*) echo "Usage: dashboard_user.sh NAME [remove]; NAME uses letters, digits, . _ -" >&2; exit 1 ;;
esac
users=/etc/caddy/dashboard_users
umask 027
trap 'rm -f "$users.tmp"; stty echo 2>/dev/null || true' EXIT
touch "$users"
grep -v "^$name " "$users" > "$users.tmp" || true
if [ "${2:-}" = remove ]; then
	if [ ! -s "$users.tmp" ]; then echo "Refusing to remove the last login" >&2; exit 1; fi
	echo "Removed $name"
else
	stty -echo
	printf "Password for %s (12+ characters, hidden): " "$name"; read -r pw; echo
	printf "Repeat it: "; read -r again; echo
	stty echo
	[ "$pw" = "$again" ] || { echo "Passwords differ" >&2; exit 1; }
	[ "${#pw}" -ge 12 ] || { echo "Use at least 12 characters" >&2; exit 1; }
	hash=$(printf '%s\n' "$pw" | caddy hash-password)
	echo "$name $hash" >> "$users.tmp"
	echo "Saved $name"
fi
chgrp caddy "$users.tmp"
mv "$users.tmp" "$users"
systemctl reload caddy
