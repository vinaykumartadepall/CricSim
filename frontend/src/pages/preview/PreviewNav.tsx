import { useNavigate } from 'react-router-dom'

const OPTIONS = [
  { key: 'pavilion',   label: 'A · The Pavilion' },
  { key: 'floodlit',   label: 'B · Floodlit'     },
  { key: 'broadsheet', label: 'C · Broadsheet'   },
  { key: 'ember',      label: 'D · Ember'         },
] as const

type PreviewKey = typeof OPTIONS[number]['key']

export function PreviewNav({ current }: { current: PreviewKey }) {
  const navigate = useNavigate()
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 900,
      background: 'rgba(8,8,8,0.94)',
      backdropFilter: 'blur(14px)',
      WebkitBackdropFilter: 'blur(14px)',
      borderBottom: '1px solid rgba(255,255,255,0.07)',
      display: 'flex', alignItems: 'center',
      padding: '0 16px', height: 44,
      fontFamily: 'system-ui, sans-serif',
    }}>
      <button
        onClick={() => navigate('/')}
        style={{
          fontSize: 12, color: '#666', background: 'none', border: 'none',
          cursor: 'pointer', padding: '0 14px 0 0',
          borderRight: '1px solid rgba(255,255,255,0.08)',
          marginRight: 14, height: '100%',
          display: 'flex', alignItems: 'center', gap: 4,
          transition: 'color 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = '#aaa'}
        onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = '#666'}
      >
        ← Exit
      </button>

      <span style={{
        fontSize: 10, color: '#444', marginRight: 10,
        letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600,
      }}>
        Theme Preview
      </span>

      <div style={{ display: 'flex', gap: 2 }}>
        {OPTIONS.map(o => (
          <button
            key={o.key}
            onClick={() => navigate(`/preview/${o.key}`)}
            style={{
              fontSize: 12,
              padding: '5px 13px',
              background: o.key === current ? 'rgba(255,255,255,0.1)' : 'transparent',
              color: o.key === current ? '#fff' : '#555',
              border: 'none', borderRadius: 5, cursor: 'pointer',
              fontWeight: o.key === current ? 600 : 400,
              transition: 'all 0.12s',
              letterSpacing: '0.01em',
            }}
            onMouseEnter={e => {
              if (o.key !== current) (e.currentTarget as HTMLElement).style.color = '#ccc'
            }}
            onMouseLeave={e => {
              if (o.key !== current) (e.currentTarget as HTMLElement).style.color = '#555'
            }}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}
