/**
 * Trade Audio — synthetic notification sounds using Web Audio API.
 *
 * Generates two distinct sounds:
 *   - BUY: bright ascending tone (green flash)
 *   - SELL: deep descending tone (red flash)
 *
 * No external audio files needed — pure oscillator synthesis.
 */

const TradeAudio = {
    _ctx: null,
    _enabled: localStorage.getItem('trade-sounds') !== 'off',
    _lastTradeId: {},  // Track last seen trade IDs per session to avoid re-playing

    // ── Context (lazy init, resumes on user gesture) ──────────────────
    get context() {
        if (!this._ctx) {
            this._ctx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (this._ctx.state === 'suspended') {
            this._ctx.resume();
        }
        return this._ctx;
    },

    // ── Toggle ────────────────────────────────────────────────────────
    toggle() {
        this._enabled = !this._enabled;
        localStorage.setItem('trade-sounds', this._enabled ? 'on' : 'off');
        return this._enabled;
    },

    get enabled() {
        return this._enabled;
    },

    // ── BUY sound: ascending major arpeggio (C4 → E4 → G4 → C5) ────
    playBuy() {
        if (!this._enabled) return;
        const ctx = this.context;
        const now = ctx.currentTime;

        // C4
        this._tone(ctx, 261.63, now, 0.15, 0.12, 'sine');
        // E4
        this._tone(ctx, 329.63, now + 0.15, 0.15, 0.12, 'sine');
        // G4
        this._tone(ctx, 392.00, now + 0.30, 0.15, 0.12, 'sine');
        // C5 (bright finish)
        this._tone(ctx, 523.25, now + 0.45, 0.30, 0.15, 'sine');
    },

    // ── SELL sound: descending minor descent (C5 → Ab4 → Eb4 → C4) ──
    playSell() {
        if (!this._enabled) return;
        const ctx = this.context;
        const now = ctx.currentTime;

        // C5
        this._tone(ctx, 523.25, now, 0.15, 0.12, 'sine');
        // Ab4
        this._tone(ctx, 440.00, now + 0.15, 0.15, 0.12, 'sine');
        // Eb4
        this._tone(ctx, 311.13, now + 0.30, 0.15, 0.12, 'sine');
        // C4 (deep finish)
        this._tone(ctx, 261.63, now + 0.45, 0.30, 0.15, 'sine');
    },

    // ── Single oscillator tone ────────────────────────────────────────
    _tone(ctx, freq, startTime, duration, volume, type = 'sine') {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = type;
        osc.frequency.setValueAtTime(freq, startTime);

        gain.gain.setValueAtTime(0, startTime);
        gain.gain.linearRampToValueAtTime(volume, startTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(startTime);
        osc.stop(startTime + duration + 0.01);
    },

    // ── Check if a new trade was opened (compare against last known) ──
    checkNewTrades(sessionId, trades) {
        if (!this._enabled || !trades) return;

        const last = this._lastTradeId[sessionId] || {};
        if (!this._lastTradeId[sessionId]) this._lastTradeId[sessionId] = last;

        for (const trade of trades) {
            const tid = trade.id || trade.metaapi_trade_id;
            if (!last[tid]) {
                last[tid] = true;
                if (trade.side === 'buy') {
                    this.playBuy();
                    this._flashScreen('buy');
                } else if (trade.side === 'sell') {
                    this.playSell();
                    this._flashScreen('sell');
                }
            }
        }

        this._lastTradeId[sessionId] = last;
    },

    // ── Visual flash on trade ────────────────────────────────────────
    _flashScreen(side) {
        const overlay = document.createElement('div');
        overlay.className = 'trade-flash';
        overlay.style.cssText = `
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            z-index: 99999; pointer-events: none;
            background: ${side === 'buy'
                ? 'rgba(16, 185, 129, 0.15)'
                : 'rgba(239, 68, 68, 0.15)'};
            animation: flashFade 0.8s ease-out forwards;
        `;
        document.body.appendChild(overlay);
        setTimeout(() => overlay.remove(), 800);
    }
};

// Inject CSS animation keyframes for the flash
const _flashStyle = document.createElement('style');
_flashStyle.textContent = `
@keyframes flashFade {
    0%   { opacity: 1; }
    100% { opacity: 0; }
}`;
document.head.appendChild(_flashStyle);
