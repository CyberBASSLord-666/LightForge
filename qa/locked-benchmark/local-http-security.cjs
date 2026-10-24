'use strict';

// Binding loopback alone does not stop a hostile DNS name resolving to it.
// Accept only the literal origin used by our browser runners, before opening
// any local assets or user-supplied audio. Forwarded headers are not trusted.
function allowLocalRequest(request, response) {
  const port = request.socket.localPort;
  // Browsers omit :80 from HTTP Host and Origin, even when the URL supplied
  // by the preview-port override explicitly includes it.
  const authority = port === 80 ? '127.0.0.1' : '127.0.0.1:' + port;
  const origin = 'http://' + authority;
  if (!Number.isInteger(port) || request.headers.host !== authority ||
      (request.headers.origin !== undefined && request.headers.origin !== origin) ||
      request.headers['sec-fetch-site'] === 'cross-site') {
    response.writeHead(403, { 'Content-Type': 'text/plain', 'Cache-Control': 'no-store' });
    response.end('Forbidden');
    return false;
  }
  response.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  return true;
}
module.exports = { allowLocalRequest };
