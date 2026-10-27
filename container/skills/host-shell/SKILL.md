# host-shell

Run commands directly on the NanoClaw host machine.

## Usage

```bash
host-cmd <command>
```

The `host-cmd` tool is available at `/usr/local/bin/host-cmd`. It runs any shell command on the host and returns stdout, stderr, and the exit code.

## Examples

```bash
# System info
host-cmd hostname
host-cmd uname -a
host-cmd df -h
host-cmd free -h
host-cmd uptime

# Network / Tailscale
host-cmd tailscale status
host-cmd tailscale ip -4
host-cmd ip addr show

# Services
host-cmd systemctl status nanoclaw
host-cmd systemctl list-units --state=failed

# GitHub CLI (authenticated as the host user)
host-cmd gh repo list
host-cmd gh pr list --repo owner/repo
host-cmd gh run list --repo owner/repo --limit 5

# Docker
host-cmd docker ps
host-cmd docker images

# Processes / resources
host-cmd ps aux --sort=-%cpu | head -15
```

## Notes

- Commands run as the NanoClaw service user (root on this machine)
- Output is capped at 1 MB; use `| head` or `| grep` for large outputs
- Default timeout: 30 seconds (adjust by passing a longer prompt if needed)
- The socket `/host/cmd.sock` must be present — it's always mounted by the container runner
