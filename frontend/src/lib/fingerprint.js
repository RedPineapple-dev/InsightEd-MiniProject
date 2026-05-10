/**
 * Generate a stable fingerprint for a video file without ever reading its contents.
 * Used by the Continue-Watching feature to recognise the same upload across sessions.
 *
 * Fingerprint = SHA-256( filename | size | lastModified )
 */

async function sha256Hex(input) {
  const data = new TextEncoder().encode(input)
  const buf = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export async function fingerprintFile(file) {
  if (!file) throw new Error('No file provided')
  const seed = `${file.name}|${file.size}|${file.lastModified}`
  return sha256Hex(seed)
}

export function describeFile(file) {
  return {
    filename: file.name,
    size_bytes: file.size,
    last_modified_ms: file.lastModified,
  }
}
