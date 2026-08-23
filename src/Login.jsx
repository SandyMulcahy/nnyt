import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './Login.css';
import { api, getToken, setToken } from './api.js';

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('Log in, or sign up for a new account');
  const [busy, setBusy] = useState(false);

  // Already signed in from a previous visit? Skip straight to the puzzle.
  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then(() => navigate('/play', { replace: true }))
      .catch(() => {});
  }, [navigate]);

  const submit = async (action) => {
    if (busy) return;
    if (!username.trim() || !password) {
      setMessage('Enter a username and password');
      return;
    }

    setBusy(true);
    try {
      const data = await action(username.trim(), password);
      setToken(data.token);
      navigate('/play', { replace: true });
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="signup-container">
      <div className="signup-wrapper">
        <h1>Daily Games</h1>

        <form
          className="signup-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit(api.login);
          }}
        >
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <button type="submit" className="login-btn" disabled={busy}>
            Log in
          </button>
        </form>

        <button
          type="button"
          className="signup-btn"
          disabled={busy}
          onClick={() => submit(api.signup)}
        >
          Sign up
        </button>

        <div className="labelText">
          <p>{message}</p>
        </div>
      </div>
    </div>
  );
}
