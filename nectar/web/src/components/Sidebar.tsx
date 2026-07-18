import type { JSX } from 'react';

export type Section =
  | 'compose'
  | 'browse'
  | 'plan'
  | 'grocery'
  | 'videos'
  | 'settings';

// Minimal stroke icons (no icon-font dependency; crisp at the nav size). Each is a 20x20 currentColor
// glyph so it inherits the nav item's color state.
const icons: Record<Section, JSX.Element> = {
  compose: (
    <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 3h9l3 3v11H4z" />
      <path d="M7 8h6M7 11h6M7 14h4" />
    </svg>
  ),
  browse: (
    <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="9" r="5.5" />
      <path d="M13.5 13.5 17 17" />
    </svg>
  ),
  plan: (
    <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="14" height="13" rx="1.5" />
      <path d="M3 8h14M7 2.5v3M13 2.5v3" />
    </svg>
  ),
  grocery: (
    <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 4h2l1.6 8.5h8L17 6.5H6" />
      <circle cx="8" cy="16" r="1" />
      <circle cx="14" cy="16" r="1" />
    </svg>
  ),
  videos: (
    <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="10" height="10" rx="1.5" />
      <path d="M13 8.5 17 6v8l-4-2.5z" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4" />
    </svg>
  ),
};

const NAV: { id: Section; label: string; group: 'primary' | 'secondary' }[] = [
  { id: 'compose', label: 'Compose', group: 'primary' },
  { id: 'browse', label: 'Recipe browser', group: 'primary' },
  { id: 'plan', label: 'Meal planner', group: 'primary' },
  { id: 'grocery', label: 'Grocery list', group: 'primary' },
  { id: 'videos', label: 'Demonstration videos', group: 'secondary' },
  { id: 'settings', label: 'Settings', group: 'secondary' },
];

interface Props {
  active: Section;
  onNavigate: (s: Section) => void;
}

export function Sidebar({ active, onNavigate }: Props): JSX.Element {
  const item = (n: (typeof NAV)[number]): JSX.Element => (
    <button
      key={n.id}
      className={`nav-item ${active === n.id ? 'on' : ''}`}
      onClick={() => onNavigate(n.id)}
      aria-current={active === n.id ? 'page' : undefined}
    >
      <span className="nav-icon">{icons[n.id]}</span>
      <span className="nav-label">{n.label}</span>
    </button>
  );

  return (
    <nav className="sidebar" aria-label="Primary">
      <div className="nav-group">{NAV.filter((n) => n.group === 'primary').map(item)}</div>
      <div className="nav-sep" />
      <div className="nav-group">{NAV.filter((n) => n.group === 'secondary').map(item)}</div>
    </nav>
  );
}
