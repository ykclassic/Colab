'use client';

import { useEffect, useState } from 'react';
import { Event, getEvents } from '../lib';

export default function NotificationsPage() {
  const [events, setEvents] = useState<Event[]>([]);
  useEffect(() => { getEvents().then(setEvents).catch(() => setEvents([])); }, []);
  return <div><header className="page-head"><div><div className="eyebrow">Productization · Notifications</div><h1>Notifications</h1><p>Operational signals, workflow changes and failures in one chronological stream.</p></div></header><section className="card section">{events.map((e, i) => <div className="row" key={`${e.event_type}-${i}`}><div><strong>{e.event_type}</strong><div className="muted">{e.message}</div><small>{e.actor}{e.occurred_at ? ` · ${new Date(e.occurred_at).toLocaleString()}` : ''}</small></div><span className="pill">{e.level}</span></div>)}{!events.length && <div className="empty">No notifications available.</div>}</section></div>;
}
