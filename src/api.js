// Thin fetch wrapper. Always same-origin: in development Vite proxies /api to
// the Flask server, in production Vercel routes it to the Python function.

const TOKEN_KEY = 'nnyt.token';

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function setToken(token) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private browsing; the session just won't persist */
  }
}

export function clearToken() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = 'GET', body } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('Could not reach the server', 0);
  }

  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = {};
    }
  }

  if (!response.ok) {
    throw new ApiError(data.error || 'Something went wrong', response.status);
  }
  return data;
}

export const api = {
  signup: (username, password) =>
    request('/auth/signup', { method: 'POST', body: { username, password } }),
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: { username, password } }),
  me: () => request('/me'),
  puzzle: () => request('/puzzle'),
  startPuzzle: () => request('/puzzle/start', { method: 'POST' }),
  submitPuzzle: (grid) => request('/puzzle/submit', { method: 'POST', body: { grid } }),
  leaderboard: () => request('/leaderboard'),
};
