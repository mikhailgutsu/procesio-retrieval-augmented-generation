import { useEffect, useState } from 'react'
import { apiBase, health } from '../api.ts'
import type { HealthResponse } from '../types.ts'

type State =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HealthResponse }
  | { kind: 'down'; message: string }

/** Small live indicator of backend + DB status, polled every 15s. */
export function HealthBadge() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const data = await health()
        if (alive) setState({ kind: 'ok', data })
      } catch (err) {
        if (alive) setState({ kind: 'down', message: (err as Error).message })
      }
    }
    check()
    const id = setInterval(check, 15000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const dbConnected = state.kind === 'ok' && state.data.database === 'connected'
  const tone = state.kind === 'loading' ? 'idle' : dbConnected ? 'up' : 'down'

  const label =
    state.kind === 'loading'
      ? 'checking backend…'
      : state.kind === 'down'
        ? 'backend offline'
        : dbConnected
          ? 'backend online'
          : 'backend up · DB offline'

  return (
    <div className={`health health--${tone}`} title={`API: ${apiBase()}`}>
      <span className="health__dot" />
      <span className="health__label">{label}</span>
      {state.kind === 'ok' && state.data.documents != null && (
        <span className="health__counts">
          {state.data.documents} docs · {state.data.chunks ?? 0} chunks
        </span>
      )}
    </div>
  )
}
