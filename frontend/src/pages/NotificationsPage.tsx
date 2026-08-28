import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listNotifications, markNotificationRead, type CommunityNotification } from '../api/community';

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<CommunityNotification[]>([]);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    listNotifications().then(setNotifications).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }
  useEffect(refresh, []);

  async function read(notification: CommunityNotification) {
    if (!notification.read_at) await markNotificationRead(notification.id);
    refresh();
  }

  return (
    <section>
      <p className="eyebrow">Account</p><h1>Notifications</h1>
      {error && <p className="error">{error}</p>}
      {!error && notifications.length === 0 && <p className="hint">You’re all caught up.</p>}
      {notifications.map((notification) => (
        <article className="card" key={notification.id}>
          <p><strong>{notification.kind.replace(/_/g, ' ')}</strong></p>
          <p className="hint">{new Date(notification.created_at).toLocaleString()}</p>
          {!notification.read_at && <button type="button" onClick={() => read(notification)}>Mark as read</button>}
        </article>
      ))}
      <p className="hint"><Link to="/account">Manage account and profile</Link></p>
    </section>
  );
}