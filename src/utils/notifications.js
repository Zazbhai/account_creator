/**
 * Browser notification utility functions
 */

/**
 * Request notification permission from the user
 * @returns {Promise<boolean>} True if permission is granted, false otherwise
 */
export async function requestNotificationPermission() {
  if (!('Notification' in window)) {
    console.warn('[Notifications] Browser does not support notifications')
    return false
  }

  if (Notification.permission === 'granted') {
    return true
  }

  if (Notification.permission === 'denied') {
    console.warn('[Notifications] Notification permission denied by user')
    return false
  }

  // Permission is 'default' - request it
  try {
    const permission = await Notification.requestPermission()
    return permission === 'granted'
  } catch (error) {
    console.error('[Notifications] Error requesting permission:', error)
    return false
  }
}

/**
 * Show a browser notification
 * @param {string} title - Notification title
 * @param {object} options - Notification options (body, icon, etc.)
 * @returns {Notification|null} The notification object or null if failed
 */
export function showNotification(title, options = {}) {
  if (!('Notification' in window)) {
    console.warn('[Notifications] Browser does not support notifications')
    return null
  }

  if (Notification.permission !== 'granted') {
    console.warn('[Notifications] Notification permission not granted')
    return null
  }

  try {
    const notification = new Notification(title, {
      icon: '/favicon.ico', // You can add a custom icon later
      badge: '/favicon.ico',
      requireInteraction: false, // Auto-close after a few seconds
      ...options
    })

    // Auto-close after 5 seconds
    setTimeout(() => {
      notification.close()
    }, 5000)

    return notification
  } catch (error) {
    console.error('[Notifications] Error showing notification:', error)
    return null
  }
}

/**
 * Show notification when account creation completes
 * @param {number} success - Number of successful accounts
 * @param {number} failed - Number of failed accounts
 * @param {number} total - Total number of accounts
 */
export function notifyAccountCompletion(success, failed, total) {
  const title = 'Account Creation Complete!'
  const body = `✅ Successful: ${success}\n❌ Failed: ${failed}\n📊 Total: ${total}`
  
  showNotification(title, {
    body: body,
    tag: 'account-completion', // Replace previous notifications with same tag
    renotify: true
  })
}
