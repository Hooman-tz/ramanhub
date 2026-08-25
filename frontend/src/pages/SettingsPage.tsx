import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { updateMyProfile, type User } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { useToast } from '../components/Toast';
import { Button, Card, InputField, Skeleton, TextareaField } from '../components/ui';

/** Mirrors the backend's `UserUpdate` validators (app/schemas/auth.py) so a
 * bad value is caught before a round trip. Kept deliberately loose where the
 * server is loose — client validation that is STRICTER than the server's
 * rejects values the server would have accepted, which is its own bug. */
const HANDLE_RE = /^[a-z0-9](?:[a-z0-9_-]{1,28})[a-z0-9]$/;
const ORCID_RE = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/;
const BIO_MAX = 1000;
const AFFILIATION_MAX = 200;

type Draft = {
  display_name: string;
  handle: string;
  affiliation: string;
  orcid_id: string;
  bio: string;
};

function draftFrom(user: User): Draft {
  return {
    display_name: user.display_name ?? '',
    handle: user.handle ?? '',
    affiliation: user.affiliation ?? '',
    orcid_id: user.orcid_id ?? '',
    bio: user.bio ?? '',
  };
}

function validate(draft: Draft): Partial<Record<keyof Draft, string>> {
  const errors: Partial<Record<keyof Draft, string>> = {};
  if (draft.handle && !HANDLE_RE.test(draft.handle)) {
    errors.handle =
      'Lowercase letters, digits, dashes and underscores; 3–30 characters; must start and end with a letter or digit.';
  }
  if (draft.orcid_id && !ORCID_RE.test(draft.orcid_id)) {
    errors.orcid_id = 'Format is 0000-0002-1825-0097.';
  }
  if (draft.bio.length > BIO_MAX) errors.bio = `${draft.bio.length} / ${BIO_MAX} characters.`;
  if (draft.affiliation.length > AFFILIATION_MAX) {
    errors.affiliation = `${draft.affiliation.length} / ${AFFILIATION_MAX} characters.`;
  }
  return errors;
}

/** Edit your own profile.
 *
 * This page did not exist: `updateMyProfile` had been written and the
 * `PATCH /users/me` endpoint worked, but nothing in the app called it, so
 * there was literally no way for a user to set their own handle or bio. That
 * matters more than it sounds — the handle is what goes in a citation. */
export default function SettingsPage() {
  const { user, loading } = useAuth();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (user) setDraft(draftFrom(user));
  }, [user]);

  if (loading) return <Skeleton lines={5} height="2rem" />;

  if (!user) {
    return (
      <Card title="Sign in to edit your profile">
        <p className="hint">
          Your profile is what a citation points at, so it needs an account.{' '}
          <Link to="/login">Sign in</Link>.
        </p>
      </Card>
    );
  }

  if (user.is_guest) {
    return (
      <Card title="Guest sessions don't have a profile">
        <p className="hint">
          You can upload and process spectra as a guest, but publishing and a citable{' '}
          <code>@handle</code> need a real account. <Link to="/login">Sign in</Link> and the
          work from this session comes with you.
        </p>
      </Card>
    );
  }

  if (!draft) return <Skeleton lines={5} height="2rem" />;

  const errors = validate(draft);
  const hasErrors = Object.keys(errors).length > 0;
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftFrom(user));

  function set<K extends keyof Draft>(key: K, value: string) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  async function save() {
    if (!draft || hasErrors) return;
    setSaving(true);
    setServerError(null);
    try {
      // Empty strings are sent as-is rather than omitted: the user clearing a
      // field is a deliberate "remove this", not "leave it alone".
      await updateMyProfile({
        display_name: draft.display_name,
        handle: draft.handle,
        affiliation: draft.affiliation,
        orcid_id: draft.orcid_id,
        bio: draft.bio,
      });
      toast.notify('Profile saved.', 'success');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // 409 is the one failure a user can actually act on, so it gets its
      // own wording instead of a raw API error string.
      setServerError(
        message.includes('409')
          ? `The handle “${draft.handle}” is already taken. Try another.`
          : message.replace(/^API error \d+:\s*/, ''),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1>Profile settings</h1>
      <p className="hint">
        This is what other scientists see, and what a citation of your data points at.
      </p>

      <Card title="Identity">
        <InputField
          label="Display name"
          value={draft.display_name}
          onChange={(e) => set('display_name', e.target.value)}
          full
        />
        <InputField
          label="Handle"
          value={draft.handle}
          onChange={(e) => set('handle', e.target.value.toLowerCase())}
          error={errors.handle}
          hint={
            draft.handle
              ? `Your profile will be at /u/${draft.handle}. Changing it keeps the old address working as a redirect — handles end up in papers, so they must not break.`
              : 'The short name people cite you by.'
          }
          full
        />
        <InputField
          label="Affiliation"
          value={draft.affiliation}
          onChange={(e) => set('affiliation', e.target.value)}
          error={errors.affiliation}
          hint="Department and institution."
          full
        />
        <InputField
          label="ORCID iD"
          value={draft.orcid_id}
          onChange={(e) => set('orcid_id', e.target.value)}
          error={errors.orcid_id}
          hint="Shown as self-reported. We don't verify iDs yet, so no badge is displayed — a badge on an unverified field would be worth less than nothing."
          placeholder="0000-0002-1825-0097"
          full
        />
      </Card>

      <Card title="About you">
        <TextareaField
          label="Bio"
          value={draft.bio}
          onChange={(e) => set('bio', e.target.value)}
          error={errors.bio}
          hint={`${draft.bio.length} / ${BIO_MAX} characters. What you work on — techniques, materials, instruments.`}
          rows={5}
          full
        />
      </Card>

      {serverError && <p className="error">{serverError}</p>}

      <div className="settings-actions">
        <Button variant="primary" onClick={save} disabled={!dirty || hasErrors} loading={saving}>
          Save changes
        </Button>
        <Button variant="ghost" onClick={() => setDraft(draftFrom(user))} disabled={!dirty}>
          Discard
        </Button>
        {user.handle && (
          <Link to={`/u/${user.handle}`} className="hint">
            View your public profile
          </Link>
        )}
      </div>
    </div>
  );
}
