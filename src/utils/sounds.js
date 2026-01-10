/**
 * Sound utility functions for playing audio feedback
 */

/**
 * Play a beep sound using Web Audio API
 * @param {number} frequency - Frequency in Hz (default: 440)
 * @param {number} duration - Duration in milliseconds (default: 200)
 * @param {string} type - Waveform type: 'sine', 'square', 'sawtooth', 'triangle' (default: 'sine')
 */
export function playBeep(frequency = 440, duration = 200, type = 'sine') {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)()
    const oscillator = audioContext.createOscillator()
    const gainNode = audioContext.createGain()

    oscillator.connect(gainNode)
    gainNode.connect(audioContext.destination)

    oscillator.frequency.value = frequency
    oscillator.type = type

    // Fade out to avoid clicks
    gainNode.gain.setValueAtTime(0.3, audioContext.currentTime)
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + duration / 1000)

    oscillator.start(audioContext.currentTime)
    oscillator.stop(audioContext.currentTime + duration / 1000)
  } catch (error) {
    console.warn('Failed to play sound:', error)
  }
}

/**
 * Play a start sound (higher-pitched, shorter beep)
 */
export function playStartSound() {
  playBeep(800, 150, 'sine')
}

/**
 * Play a completion sound (lower-pitched, longer beep with two tones)
 */
export function playCompletionSound() {
  // Play two tones for completion
  playBeep(600, 200, 'sine')
  setTimeout(() => {
    playBeep(500, 300, 'sine')
  }, 150)
}

