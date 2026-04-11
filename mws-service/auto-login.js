/**
 * Auto-login helper for TiddlyWiki MWS.
 *
 * Provides a simple HTTP endpoint that injects an admin session into the MWS
 * SQLite database and sets the session cookie in the browser, then redirects
 * to the wiki. This allows browser users to access wikis without going through
 * the OPAQUE authentication flow.
 *
 * Usage:
 *   GET http://localhost:8081/auto-login          → sets cookie & redirects to MWS home
 *   GET http://localhost:8081/auto-login?wiki=slug  → sets cookie & redirects to /wiki/slug
 */

const http = require('http');
const { execSync } = require('child_process');
const path = require('path');
const crypto = require('crypto');
const Database = require('better-sqlite3');

const DB_PATH = process.env.MWS_DB_PATH || '/data/store/database.sqlite';
const ADMIN_USER = process.env.MWS_ADMIN_USER || 'admin';
const MWS_URL = process.env.MWS_URL || 'http://localhost:8080';
const PORT = parseInt(process.env.AUTO_LOGIN_PORT || '8081', 10);

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname === '/auto-login') {
    try {
      const sessionId = injectSession();
      const wiki = url.searchParams.get('wiki') || '';
      const redirectUrl = wiki ? `${MWS_URL}/wiki/${wiki}` : MWS_URL;

      res.writeHead(302, {
        'Set-Cookie': `session=${sessionId}; Path=/; HttpOnly`,
        'Location': redirectUrl,
      });
      res.end();
    } catch (err) {
      console.error('Auto-login error:', err.message);
      res.writeHead(500, { 'Content-Type': 'text/plain' });
      res.end(`Auto-login failed: ${err.message}`);
    }
  } else if (url.pathname === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok' }));
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found. Use /auto-login to log in to MWS.');
  }
});

function injectSession() {
  const db = new Database(DB_PATH);
  db.pragma('journal_mode=WAL');

  // Find admin user
  const user = db.prepare('SELECT user_id FROM users WHERE username = ?').get(ADMIN_USER);
  if (!user) {
    db.close();
    throw new Error(`User '${ADMIN_USER}' not found`);
  }

  // Delete old sessions for this user (clean up)
  db.prepare('DELETE FROM sessions WHERE user_id = ?').run(user.user_id);

  // Create new session
  const sessionId = crypto.randomBytes(16).toString('base64url');
  const sessionKey = crypto.randomBytes(32).toString('base64url');
  const now = new Date().toISOString();

  db.prepare(
    'INSERT INTO sessions (session_id, created_at, last_accessed, session_key, user_id) VALUES (?, ?, ?, ?, ?)'
  ).run(sessionId, now, now, sessionKey, user.user_id);

  db.close();
  console.log(`[${new Date().toISOString()}] Auto-login: created session ${sessionId} for user '${ADMIN_USER}'`);
  return sessionId;
}

server.listen(PORT, () => {
  console.log(`MWS Auto-login helper running on port ${PORT}`);
  console.log(`  GET http://localhost:${PORT}/auto-login         → login & redirect to MWS home`);
  console.log(`  GET http://localhost:${PORT}/auto-login?wiki=X   → login & redirect to /wiki/X`);
});