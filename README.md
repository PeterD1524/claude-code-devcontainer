# claude-code-devcontainer

https://code.claude.com/docs/en/devcontainer

> The reference devcontainer setup and associated Dockerfile offer a preconfigured development container that you can use as is, or customize for your needs.

https://github.com/devcontainers/cli

https://containers.dev/supporting#devcontainer-cli

```
devcontainer up --docker-path podman --remove-existing-container
```

```
devcontainer exec --docker-path podman -- fish
```

NOTES

- iptables commands require --cap-add=NET_ADMIN.
- Replaces iptables with iptables-nft.
