# Reporting without exposing a home

Do not post raw Home Assistant traces, generated packages, settings files, maps, screenshots with coordinates, serial numbers, device IDs, tokens or household presence history. Those artifacts may contain private data even when no password is visible.

For an ordinary bug, provide a synthetic reproduction, package version, integration/firmware version, expected behavior and redacted state transitions. Review attachments locally before uploading. For a security issue, use the repository's private reporting channel if available. If it is unavailable, first ask for a private contact route without disclosing the issue's sensitive details.

This package has no cloud service, telemetry upload or credential store. Its compiler runs locally. The integration and Home Assistant retain their own network and authentication behavior. Optional local mobile notifications may include runtime location in their message; review those actions before enabling them.
