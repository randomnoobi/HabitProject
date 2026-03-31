"""
pipeline/state.py — Real-Time danger/safe decision logic.

Chart stage: "RT → branch into: 1. distance is dangerous  2. all distance > safe distance"

This is the state machine that:
  - Tracks whether the desk is currently in SAFE or DANGEROUS state
  - In DANGEROUS state, decides when to send updates (every 1 minute per chart)
  - In SAFE state, tracks that no update is needed
  - Per the chart: "if Ollama does not receive after 1 minute, is safe"
"""

import time
from pipeline.config import DANGER_UPDATE_INTERVAL, SAFE_CONFIRM_FRAMES


# State constants
SAFE = 'SAFE'
DANGEROUS = 'DANGEROUS'


class SafetyState:
    """
    State machine that manages the danger/safe branching logic.

    Transition rules:
        SAFE → DANGEROUS:  when any pair distance < threshold
        DANGEROUS → SAFE:  when ALL pairs safe for SAFE_CONFIRM_FRAMES consecutive frames
    """

    def __init__(self):
        self.state = SAFE
        self.last_update_time = 0         # timestamp of last Ollama update
        self.danger_start_time = 0        # when the current danger period began
        self.consecutive_safe_frames = 0  # for debouncing back to SAFE
        self.total_danger_updates = 0     # how many updates sent this danger period

    def update(self, is_dangerous):
        """
        Feed one frame's danger/safe result into the state machine.

        Args:
            is_dangerous: bool — True if any monitored pair is too close.

        Returns:
            dict with:
                - state: "SAFE" or "DANGEROUS"
                - should_send: bool — True if it's time to send an Ollama update
                - transitioned: bool — True if state just changed this frame
                - seconds_in_state: float
        """
        now = time.time()
        transitioned = False

        if is_dangerous:
            self.consecutive_safe_frames = 0

            if self.state == SAFE:
                # Transition: SAFE → DANGEROUS
                self.state = DANGEROUS
                self.danger_start_time = now
                self.last_update_time = 0
                self.total_danger_updates = 0
                transitioned = True

        else:
            self.consecutive_safe_frames += 1

            if self.state == DANGEROUS:
                if self.consecutive_safe_frames >= SAFE_CONFIRM_FRAMES:
                    # Transition: DANGEROUS → SAFE
                    self.state = SAFE
                    transitioned = True
                    self.consecutive_safe_frames = 0

        # Determine if we should send an update right now
        should_send = False
        if self.state == DANGEROUS:
            elapsed = now - self.last_update_time
            if self.last_update_time == 0 or elapsed >= DANGER_UPDATE_INTERVAL:
                should_send = True

        seconds_in_state = now - self.danger_start_time if self.state == DANGEROUS else 0

        return {
            'state': self.state,
            'should_send': should_send,
            'transitioned': transitioned,
            'seconds_in_state': round(seconds_in_state, 1),
        }

    def mark_sent(self):
        """Call this after successfully sending an update to Ollama."""
        self.last_update_time = time.time()
        self.total_danger_updates += 1

    @property
    def status_line(self):
        """One-line status for logging."""
        if self.state == SAFE:
            return 'State: SAFE — no dangerous distances detected'
        elapsed = time.time() - self.danger_start_time
        return (
            f'State: DANGEROUS — {elapsed:.0f}s in danger, '
            f'{self.total_danger_updates} updates sent'
        )
