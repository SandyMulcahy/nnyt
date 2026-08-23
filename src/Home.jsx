import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './Home.css';
import Leaderboard from './components/Leaderboard.jsx';
import Crossword from './components/Crossword.jsx';
import { api, clearToken } from './api.js';

export default function Home() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  // Bumped whenever the puzzle is solved so the leaderboard reloads immediately.
  const [leaderboardKey, setLeaderboardKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((data) => {
        if (!cancelled) setUsername(data.username);
      })
      .catch((err) => {
        if (err.status === 401) {
          clearToken();
          navigate('/', { replace: true });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const logout = () => {
    clearToken();
    navigate('/', { replace: true });
  };

  return (
    <div className="web-page">
      <div className="top-right-container">
        <h4 className="welcome-message">Hello, {username}</h4>
        <button className="btn logout-btn" onClick={logout}>
          Log Out
        </button>
      </div>

      <div className="game-layout">
        <div className="game-main">
          <Crossword onSolved={() => setLeaderboardKey((k) => k + 1)} />
        </div>

        <div className="game-sidebar">
          <Leaderboard refreshKey={leaderboardKey} />
        </div>
      </div>
    </div>
  );
}
