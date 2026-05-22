/**
 * Singleflight: collapse N concurrent calls to the same key into one.
 *
 *   const get = singleflight()
 *   await get('users', () => fetch('/users'))   // makes the request
 *   await get('users', () => fetch('/users'))   // returns the same in-flight promise
 *
 * After the promise settles, the entry is cleared so subsequent calls hit
 * the network normally. Used to prevent double-clicks on Process or
 * duplicate /status polls firing while a first one is still in flight.
 */
export function singleflight() {
  const inflight = new Map()
  return function call(key, fn) {
    if (inflight.has(key)) return inflight.get(key)
    const p = Promise.resolve()
      .then(fn)
      .finally(() => {
        inflight.delete(key)
      })
    inflight.set(key, p)
    return p
  }
}

// A shared singleflight that any module can import — keeps the keyspace
// trivial (one process-wide map keyed by URL+args).
export const globalSingleflight = singleflight()
