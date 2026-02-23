const https   = require('https');
const http    = require('http');
const express = require('express');
const app     = express();

app.get('/proxy', (req, res) => {
  const target = req.query.url;
  if (!target || !/^https:\/\/(raw\.githubusercontent\.com|github\.com|objects\.githubusercontent\.com)/i.test(target)) {
    return res.status(400).json({ error: 'URL not allowed' });
  }
  res.setHeader('Access-Control-Allow-Origin', '*');

  function fetchUrl(url, depth) {
    if (depth > 5) return res.status(500).json({ error: 'Too many redirects' });
    const client = url.startsWith('https') ? https : http;
    client.get(url, (upstream) => {
      if ([301,302,303,307,308].includes(upstream.statusCode) && upstream.headers.location) {
        return fetchUrl(upstream.headers.location, depth + 1);
      }
      res.setHeader('Content-Type', 'application/octet-stream');
      upstream.pipe(res);
    }).on('error', e => res.status(500).json({ error: e.message }));
  }
  fetchUrl(target, 0);
});

app.listen(process.env.PORT || 3000, () => console.log('Proxy running'));
