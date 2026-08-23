import React, { useEffect, useState } from 'react';
import './Leaderboard.css';
import { api } from '../api.js';

const formatTime = (seconds) => {
  const total = Math.max(0, Math.floor(seconds || 0));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};

const formatDate = (iso) => {
  if (!iso) return '';
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year}`;
};

const medal = (rank) => (rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : `#${rank}`);

export default function Leaderboard({ refreshKey = 0 }) {
  const [entries, setEntries] = useState([]);
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const data = await api.leaderboard();
        if (cancelled) return;
        setEntries(data.entries || []);
        setDate(data.date || '');
      } catch {
        /* keep whatever we last showed */
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [refreshKey]);

  return (
    <div className="leaderboard-container">
      <div className="leaderboard-header">
        <h2>LEADERBOARD</h2>
        <p className="date">{formatDate(date)}</p>
      </div>

      {loading ? (
        <div className="loading">Loading...</div>
      ) : (
        <div className="leaderboard-content">
          <div className="leaderboard-list">
            {entries.length === 0 && (
              <div className="loading">Nobody has finished yet today.</div>
            )}
            {entries.map((player) => (
              <div key={player.rank} className="leaderboard-item">
                <div className="rank">{medal(player.rank)}</div>
                <div className="player-info">
                  <div className="username">{player.username}</div>
                </div>
                <div className="time">{formatTime(player.seconds)}</div>
              </div>
            ))}
          </div>

          <div className="leaderboard-footer">
            <p className="update-info">Updates every minute</p>
          </div>
        </div>
      )}
    </div>
  );
}
