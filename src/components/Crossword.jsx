import React, { useCallback, useEffect, useRef, useState } from 'react';
import './Crossword.css';
import { api } from '../api.js';

const SIZE = 5;

const emptyGrid = () =>
  Array.from({ length: SIZE }, () => Array.from({ length: SIZE }, () => ''));

const formatTime = (seconds) => {
  const total = Math.max(0, Math.floor(seconds || 0));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
};

export default function Crossword({ onSolved }) {
  const [status, setStatus] = useState('loading'); // loading | ready | solved | error
  const [clues, setClues] = useState({ across: [], down: [], date: '' });
  const [grid, setGrid] = useState(emptyGrid);
  const [highlighted, setHighlighted] = useState({ row: 0, col: 0 });
  const [across, setAcross] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState('');

  const inputRefs = useRef(
    Array.from({ length: SIZE }, () => Array.from({ length: SIZE }, () => null))
  );
  const tickRef = useRef(null);
  const startEpochRef = useRef(null);
  const startingRef = useRef(false);
  const lastSubmittedRef = useRef('');

  const stopTimer = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  // Run the clock off a fixed start time rather than incrementing a counter,
  // so a backgrounded tab or a slow render can't drift.
  const runTimerFrom = useCallback(
    (secondsAlready) => {
      startEpochRef.current = Date.now() - secondsAlready * 1000;
      setElapsed(secondsAlready);
      stopTimer();
      tickRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startEpochRef.current) / 1000));
      }, 250);
    },
    [stopTimer]
  );

  useEffect(() => {
    let cancelled = false;

    api
      .puzzle()
      .then((data) => {
        if (cancelled) return;
        setClues({ across: data.across, down: data.down, date: data.date });

        if (data.solved) {
          setElapsed(data.elapsed_seconds || 0);
          setStatus('solved');
          return;
        }

        setStatus('ready');
        if (data.in_progress) {
          // Resume a solve that was already started on the server.
          runTimerFrom(data.elapsed_seconds || 0);
          setMessage('1: ' + (data.across[0] || ''));
        } else {
          setMessage('Click a cell to start');
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus('error');
        setMessage(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [runTimerFrom]);

  useEffect(() => stopTimer, [stopTimer]);

  // Clue text comes from data already in the browser — no request per keystroke.
  useEffect(() => {
    if (status !== 'ready' || startEpochRef.current === null) return;
    const index = across ? highlighted.row : highlighted.col;
    const clue = across ? clues.across[index] : clues.down[index];
    setMessage(`${index + 1}: ${clue || ''}`);
  }, [highlighted, across, clues, status]);

  const beginSolve = async () => {
    if (startEpochRef.current !== null || startingRef.current) return;
    startingRef.current = true;
    try {
      const data = await api.startPuzzle();
      if (data.solved) {
        setElapsed(data.elapsed_seconds || 0);
        setStatus('solved');
        return;
      }
      runTimerFrom(data.elapsed_seconds || 0);
    } catch (err) {
      setMessage(err.message);
    } finally {
      startingRef.current = false;
    }
  };

  const submit = useCallback(
    async (letters) => {
      lastSubmittedRef.current = letters;
      try {
        const result = await api.submitPuzzle(letters);
        if (!result.correct) {
          setMessage('Grid is full, but something is off');
          return;
        }
        stopTimer();
        setElapsed(result.elapsed_seconds || 0);
        setStatus('solved');
        if (onSolved) onSolved();
      } catch (err) {
        setMessage(err.message);
      }
    },
    [onSolved, stopTimer]
  );

  // Check only once the grid is completely filled, and only when it changed.
  useEffect(() => {
    if (status !== 'ready') return;
    const letters = grid.flat().join('');
    if (letters.length !== SIZE * SIZE) return;
    if (letters === lastSubmittedRef.current) return;
    submit(letters);
  }, [grid, status, submit]);

  const focusCell = (row, col) => {
    setHighlighted({ row, col });
    inputRefs.current[row][col]?.focus();
  };

  const handleCellFocus = (row, col) => {
    if (startEpochRef.current === null) {
      beginSolve();
    } else if (highlighted.row === row && highlighted.col === col) {
      setAcross((value) => !value);
    }
    setHighlighted({ row, col });
  };

  const handleInputChange = (row, col, value) => {
    const char = value
      .toUpperCase()
      .replace(/[^A-Z]/g, '')
      .slice(-1);

    // Copy the row too: mutating it in place makes React skip the re-render.
    setGrid((prev) => prev.map((r, i) => (i === row ? r.map((c, j) => (j === col ? char : c)) : r)));

    if (!char) return;

    if (across) {
      if (col < SIZE - 1) focusCell(row, col + 1);
      else if (row < SIZE - 1) focusCell(row + 1, 0);
    } else if (row < SIZE - 1) {
      focusCell(row + 1, col);
    } else if (col < SIZE - 1) {
      focusCell(0, col + 1);
    }
  };

  const handleKeyDown = (e, row, col) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setAcross((value) => !value);
      return;
    }

    if (e.key === 'Backspace' && !grid[row][col]) {
      e.preventDefault();
      if (across) {
        if (col > 0) focusCell(row, col - 1);
        else if (row > 0) focusCell(row - 1, SIZE - 1);
      } else if (row > 0) {
        focusCell(row - 1, col);
      } else if (col > 0) {
        focusCell(SIZE - 1, col - 1);
      }
      return;
    }

    if (e.key === 'ArrowUp' && row > 0) focusCell(row - 1, col);
    else if (e.key === 'ArrowDown' && row < SIZE - 1) focusCell(row + 1, col);
    else if (e.key === 'ArrowLeft' && col > 0) focusCell(row, col - 1);
    else if (e.key === 'ArrowRight' && col < SIZE - 1) focusCell(row, col + 1);
  };

  if (status === 'loading') {
    return (
      <div className="grid-wrapper">
        <h1 className="title">5 x 5</h1>
        <p className="display-text">Loading today's puzzle…</p>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="grid-wrapper">
        <h1 className="title">5 x 5</h1>
        <p className="display-text">{message}</p>
      </div>
    );
  }

  return (
    <div className="grid-wrapper">
      <h1 className="title">5 x 5</h1>

      {status === 'ready' && (
        <div>
          <div className="grid">
            {grid.map((row, rowIndex) =>
              row.map((cell, colIndex) => {
                const isHighlighted =
                  highlighted.row === rowIndex && highlighted.col === colIndex;
                const inSameLine = across
                  ? highlighted.row === rowIndex
                  : highlighted.col === colIndex;

                let cellClass = 'grid-cell';
                if (isHighlighted) cellClass += ' highlighted';
                else if (inSameLine) cellClass += ' related-cell';

                return (
                  <input
                    key={`${rowIndex}-${colIndex}`}
                    ref={(el) => {
                      inputRefs.current[rowIndex][colIndex] = el;
                    }}
                    type="text"
                    inputMode="text"
                    autoComplete="off"
                    autoCorrect="off"
                    spellCheck="false"
                    aria-label={`Row ${rowIndex + 1}, column ${colIndex + 1}`}
                    value={cell}
                    onChange={(e) => handleInputChange(rowIndex, colIndex, e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, rowIndex, colIndex)}
                    onFocus={() => handleCellFocus(rowIndex, colIndex)}
                    className={cellClass}
                  />
                );
              })
            )}
          </div>

          <p className="display-text">{message}</p>

          <div className="button-container">
            <button onClick={() => setAcross((value) => !value)} className="btn btn-acrossdown">
              Across/Down
            </button>

            <div className="timer-display">
              <span className="timer-time">{formatTime(elapsed)}</span>
            </div>
          </div>
        </div>
      )}

      {status === 'solved' && (
        <div className="modal-content">
          <h2>{formatTime(elapsed)}</h2>
          <p>Impressive!</p>
          <p>Come back tomorrow for a new puzzle.</p>
        </div>
      )}
    </div>
  );
}
