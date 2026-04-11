/**
 * mws-login.js — Node.js helper for MWS OPAQUE authentication.
 *
 * Usage: node mws-login.js <mws_url> <username> <password>
 * Output: session cookie string (e.g., "sid=abc123")
 *
 * This script performs the two-phase OPAQUE login against the
 * TiddlyWiki MultiWikiServer and outputs the session cookie
 * for use by the Python MWS client.
 */

const https = require('http'); // MWS is HTTP in internal Docker network

async function login(mwsUrl, username, password) {
  // Phase 1: Start login
  const startResponse = await fetch(`${mwsUrl}/login/1`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!startResponse.ok) {
    // Try simpler auth - some MWS configs support basic auth
    const basicResponse = await fetch(`${mwsUrl}/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'TiddlyWiki',
      },
      body: JSON.stringify({ username, password }),
    });

    if (basicResponse.ok) {
      const setCookie = basicResponse.headers.get('set-cookie');
      if (setCookie) {
        // Extract session cookie from Set-Cookie header
        const match = setCookie.match(/([^;]+)=([^;]+)/);
        if (match) {
          console.log(`${match[1]}=${match[2]}`);
          return;
        }
      }
      console.log(basicResponse.headers.get('set-cookie') || '');
      return;
    }

    throw new Error(`Login phase 1 failed: ${startResponse.status} ${await startResponse.text()}`);
  }

  const loginData = await startResponse.json();

  // Phase 2: Finish login
  const finishResponse = await fetch(`${mwsUrl}/login/2`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      finishLoginRequest: loginData.finishLoginRequest || '',
      loginSession: loginData.loginSession || '',
    }),
  });

  if (!finishResponse.ok) {
    throw new Error(`Login phase 2 failed: ${finishResponse.status}`);
  }

  // Extract session cookie from response
  const setCookie = finishResponse.headers.get('set-cookie');
  if (setCookie) {
    // Parse the cookie - extract the session cookie value
    const match = setCookie.match(/([^;]+)=([^;]+)/);
    if (match) {
      console.log(`${match[1]}=${match[2]}`);
      return;
    }
  }

  // Fallback: try to get cookie from response body
  const finishData = await finishResponse.json();
  if (finishData.session_cookie) {
    console.log(finishData.session_cookie);
  } else {
    console.log(JSON.stringify(finishData));
  }
}

const [,, mwsUrl, username, password] = process.argv;

if (!mwsUrl || !username || !password) {
  console.error('Usage: node mws-login.js <mws_url> <username> <password>');
  process.exit(1);
}

login(mwsUrl, username, password).catch(err => {
  console.error('Login failed:', err.message);
  process.exit(1);
});