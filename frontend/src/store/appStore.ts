// 전역 상태 — zustand 없이 React context + useReducer로 관리

import { createContext, useContext } from 'react'
import type {
  ConnectionState,
  PanelTab,
  RemoteConnectionState,
  SourceMode,
} from '../types'

export interface ToastItem {
  id: string
  message: string
  variant: 'error' | 'success' | 'info'
}

export interface AppState {
  mode: SourceMode
  connection: ConnectionState
  remoteConnection: RemoteConnectionState
  activeTab: PanelTab
  selectedBucket: string | null
  toasts: ToastItem[]
}

export type AppAction =
  | { type: 'SET_MODE'; payload: SourceMode }
  | { type: 'SET_CONNECTION'; payload: ConnectionState }
  | { type: 'SET_REMOTE_CONNECTION'; payload: RemoteConnectionState }
  | { type: 'SET_TAB'; payload: PanelTab }
  | { type: 'SET_BUCKET'; payload: string | null }
  | { type: 'ADD_TOAST'; payload: ToastItem }
  | { type: 'REMOVE_TOAST'; payload: string }

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_MODE':
      // 모드 전환 시 다운로드 탭으로 초기화(패널 상태 혼동 방지)
      return { ...state, mode: action.payload, activeTab: 'download' }
    case 'SET_CONNECTION':
      return { ...state, connection: action.payload }
    case 'SET_REMOTE_CONNECTION':
      return { ...state, remoteConnection: action.payload }
    case 'SET_TAB':
      return { ...state, activeTab: action.payload }
    case 'SET_BUCKET':
      return { ...state, selectedBucket: action.payload }
    case 'ADD_TOAST':
      return { ...state, toasts: [...state.toasts, action.payload] }
    case 'REMOVE_TOAST':
      return { ...state, toasts: state.toasts.filter(t => t.id !== action.payload) }
    default:
      return state
  }
}

export const initialAppState: AppState = {
  mode: 's3',
  connection: { connected: false },
  remoteConnection: { connected: false },
  activeTab: 'download',
  selectedBucket: null,
  toasts: [],
}

export interface AppContextValue {
  state: AppState
  dispatch: React.Dispatch<AppAction>
}

export const AppContext = createContext<AppContextValue | null>(null)

export function useAppStore() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppStore must be used inside AppProvider')
  return ctx
}
