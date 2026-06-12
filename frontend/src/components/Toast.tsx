import { useEffect } from 'react'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'
import { useAppStore } from '../store/appStore'

export function ToastContainer() {
  const { state, dispatch } = useAppStore()

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {state.toasts.map(toast => (
        <Toast
          key={toast.id}
          id={toast.id}
          message={toast.message}
          variant={toast.variant}
          onClose={() => dispatch({ type: 'REMOVE_TOAST', payload: toast.id })}
        />
      ))}
    </div>
  )
}

interface ToastProps {
  id: string
  message: string
  variant: 'error' | 'success' | 'info'
  onClose: () => void
}

function Toast({ message, variant, onClose }: ToastProps) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000)
    return () => clearTimeout(t)
  }, [onClose])

  const colors = {
    error: 'bg-red-900/90 border-red-700 text-red-100',
    success: 'bg-emerald-900/90 border-emerald-700 text-emerald-100',
    info: 'bg-zinc-800/90 border-zinc-700 text-zinc-100',
  }

  const Icon = variant === 'error' ? AlertCircle : variant === 'success' ? CheckCircle : Info

  return (
    <div
      className={`pointer-events-auto flex items-start gap-3 px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm max-w-sm text-sm ${colors[variant]}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <span className="flex-1">{message}</span>
      <button onClick={onClose} className="shrink-0 opacity-70 hover:opacity-100 transition-opacity">
        <X size={14} />
      </button>
    </div>
  )
}
