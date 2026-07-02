import { useRef, useState } from 'react'

interface Props {
  disabled?: boolean
  onSend: (text: string) => void
}

/** Auto-growing chat input. Enter to send, Shift+Enter for a newline. */
export function Composer({ disabled, onSend }: Props) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue('')
    if (ref.current) ref.current.style.height = 'auto'
  }

  const grow = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <textarea
        ref={ref}
        className="composer__input"
        placeholder="Ask something about the ingested documents…"
        rows={1}
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          grow(e.target)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <button type="submit" className="composer__send" disabled={disabled || !value.trim()}>
        {disabled ? '…' : 'Send'}
      </button>
    </form>
  )
}
