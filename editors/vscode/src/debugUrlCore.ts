// The address of the application under debugging (no vscode import), unit-tested under plain Node.
//
// The browser client attaches to the debug session only when its address names the debug server
// and the session, and which parameters it reads depends on the server version. Newer clients
// read `debug-server-url` (client-debug-address as is) and ignore host and port; older ones read
// `debug-server-host` and `debug-server-port` and know nothing of the url. Both kinds are in use
// at the same time, the cloud and a local server can differ. A client that finds none of its own
// parameters starts without attaching: server breakpoints still stop, client ones never do. The
// address therefore carries both sets; each client skips the other one's.
//
// The sign-in mode is `force_auth`, the query parameter the platform's authentication reads
// (the IDE plugin passes it the same way).

// Host and port out of client-debug-address (wss://host:port) for the older clients.
function hostPort(address: string): { host: string; port: string } {
  const u = new URL(address);
  return { host: u.hostname, port: u.port || (u.protocol === "wss:" ? "443" : "80") };
}

export function debuggeeUrl(appUrl: string, clientDebugAddress: string, sessionId: string, authMode?: string): string {
  const { host, port } = hostPort(clientDebugAddress);
  const params = [
    `debug-server-url=${encodeURIComponent(clientDebugAddress)}`,
    `debug-server-host=${host}`,
    `debug-server-port=${port}`,
    `debug-session-id=${sessionId}`,
  ];
  if (authMode) {
    params.push(`force_auth=${authMode}`);
  }
  const sep = appUrl.includes("?") ? "&" : "?";
  return `${appUrl}${sep}${params.join("&")}`;
}
