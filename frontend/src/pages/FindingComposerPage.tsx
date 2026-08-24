import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getLicenses, startGuestSession, type License } from '../api/client';
import { getMyLibrary, type SpectrumSearchResult } from '../api/search';
import {
  appendEntry,
  attachSpectrum,
  createFinding,
  deleteEntry,
  detachSpectrum,
  getFinding,
  publishFinding,
  updateFinding,
  type Finding,
  type FindingEntryKind,
} from '../api/findings';
import { useAuth } from '../auth/useAuth';
import FindingEntryView from '../components/FindingEntryView';
import { useToast } from '../components/Toast';
import { Button, Card, Skeleton } from '../components/ui';

const ENTRY_KINDS: Array<{ value: FindingEntryKind; label: string; hint: string }> = [
  { value: 'note', label: 'Note', hint: 'Prose — what you did, what you saw' },
  { value: 'spectra', label: 'Spectra overlay', hint: 'Plot the attached spectra together' },
  { value: 'pca', label: 'PCA', hint: 'Scores and loadings over the attached spectra' },
  { value: 'hca', label: 'Clustering', hint: 'Hierarchical clustering over the attached set' },
];

/** Create or edit a Finding.
 *
 * Deliberately saves the draft to the server before anything else can be
 * attached: entries and member spectra are rows keyed to a finding id, so a
 * purely client-side "unsaved finding" would need a parallel in-memory
 * model that behaves subtly differently from the persisted one. Creating
 * first keeps a single code path. */
export default function FindingComposerPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { notify } = useToast();

  const [finding, setFinding] = useState<Finding | null>(null);
  const [title, setTitle] = useState('');
  const [abstract, setAbstract] = useState('');
  const [tags, setTags] = useState('');
  const [doi, setDoi] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(Boolean(id));

  const [mine, setMine] = useState<SpectrumSearchResult[]>([]);
  const [entryKind, setEntryKind] = useState<FindingEntryKind>('note');
  const [entryBody, setEntryBody] = useState('');
  const [licenses, setLicenses] = useState<License[]>([]);
  const [licenseId, setLicenseId] = useState('');

  useEffect(() => {
    getLicenses()
      .then((rows) => {
        setLicenses(rows);
        if (rows.length) setLicenseId(rows[0].id);
      })
      .catch(() => {});
    getMyLibrary()
      .then(setMine)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getFinding(id)
      .then((data) => {
        setFinding(data);
        setTitle(data.title);
        setAbstract(data.abstract_md ?? '');
        setTags((data.tags ?? []).join(', '));
        setDoi(data.doi ?? '');
      })
      .catch((err) => notify(err instanceof Error ? err.message : String(err), 'error'))
      .finally(() => setLoading(false));
  }, [id, notify]);

  function parsedTags(): string[] {
    return tags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
  }

  async function handleSave() {
    if (!title.trim()) {
      notify('A finding needs a title.', 'error');
      return;
    }
    setSaving(true);
    try {
      if (!user) await startGuestSession();
      if (finding) {
        const updated = await updateFinding(finding.id, {
          title: title.trim(),
          abstract_md: abstract,
          tags: parsedTags(),
          doi: doi.trim(),
        });
        setFinding(updated);
        notify('Saved.', 'success');
      } else {
        const created = await createFinding({
          title: title.trim(),
          abstract_md: abstract,
          tags: parsedTags(),
        });
        setFinding(created);
        notify('Draft created.', 'success');
        navigate(`/findings/${created.id}/edit`, { replace: true });
      }
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handleAttach(spectrumId: string) {
    if (!finding) return;
    try {
      setFinding(await attachSpectrum(finding.id, spectrumId));
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  async function handleDetach(spectrumId: string) {
    if (!finding) return;
    try {
      setFinding(await detachSpectrum(finding.id, spectrumId));
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  async function handleAppendEntry() {
    if (!finding) return;
    try {
      const config =
        entryKind === 'note'
          ? undefined
          : { spectrum_ids: finding.spectra.map((s) => s.spectrum_id) };
      setFinding(
        await appendEntry(finding.id, { kind: entryKind, body_md: entryBody, config }),
      );
      setEntryBody('');
      notify('Entry added.', 'success');
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  async function handleDeleteEntry(entryId: string) {
    if (!finding) return;
    try {
      setFinding(await deleteEntry(finding.id, entryId));
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  async function handlePublish() {
    if (!finding) return;
    try {
      const published = await publishFinding(finding.id, licenseId);
      setFinding(published);
      notify('Published.', 'success');
      navigate(`/findings/${published.id}`);
    } catch (err) {
      // The backend names the offending spectra when a member is still
      // private, so surfacing the message verbatim is more useful than a
      // generic failure.
      notify(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  if (loading) return <Skeleton lines={6} height="2rem" />;

  const attachedIds = new Set(finding?.spectra.map((s) => s.spectrum_id) ?? []);
  const attachable = mine.filter((s) => !attachedIds.has(s.id));
  const unpublishedMembers = finding?.spectra.filter((s) => s.state !== 'published') ?? [];

  return (
    <div className="composer">
      <header className="page-head">
        <h1>{finding ? 'Edit finding' : 'Write a finding'}</h1>
        {finding && (
          <Link to={`/findings/${finding.id}`} className="ui-button">
            Preview
          </Link>
        )}
      </header>

      <Card title="The write-up">
        <label className="field">
          <span>Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What did you find?"
            maxLength={300}
          />
        </label>

        <label className="field">
          <span>Abstract</span>
          <textarea
            value={abstract}
            onChange={(e) => setAbstract(e.target.value)}
            rows={6}
            placeholder="A paragraph or two: what you measured, what you did to it, what it shows."
          />
        </label>

        <label className="field">
          <span>Tags</span>
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="sers, fluorescence, airpls"
          />
          <small className="hint">Comma-separated. Up to 10.</small>
        </label>

        {finding && (
          <label className="field">
            <span>Linked publication DOI</span>
            <input
              value={doi}
              onChange={(e) => setDoi(e.target.value)}
              placeholder="10.1021/acs.analchem…"
            />
            <small className="hint">
              Linking a peer-reviewed paper marks this finding DOI-verified.
            </small>
          </label>
        )}

        <Button variant="primary" onClick={handleSave} loading={saving}>
          {finding ? 'Save changes' : 'Create draft'}
        </Button>
      </Card>

      {!finding && (
        <p className="hint">
          Create the draft first — spectra and figures attach to a saved finding.
        </p>
      )}

      {finding && (
        <>
          <Card title={`Spectra (${finding.spectra.length})`}>
            {finding.spectra.length === 0 && (
              <p className="hint">
                Attach at least one spectrum. Publishing needs every attached spectrum to
                be published too.
              </p>
            )}
            <ul className="member-list">
              {finding.spectra.map((member) => (
                <li key={member.spectrum_id}>
                  <Link to={`/spectra/${member.spectrum_id}`}>
                    {member.label ?? member.title ?? member.accession}
                  </Link>
                  {member.state !== 'published' && (
                    <span className="chip chip--draft">{member.state}</span>
                  )}
                  <button
                    type="button"
                    className="ui-button ui-button--ghost ui-button--sm"
                    onClick={() => handleDetach(member.spectrum_id)}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>

            {attachable.length > 0 && (
              <label className="field">
                <span>Add from your library</span>
                <select
                  value=""
                  onChange={(e) => e.target.value && handleAttach(e.target.value)}
                >
                  <option value="">Choose a spectrum…</option>
                  {attachable.map((spectrum) => (
                    <option key={spectrum.id} value={spectrum.id}>
                      {spectrum.title ?? spectrum.accession ?? spectrum.id} ({spectrum.state})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </Card>

          <Card title="Thread">
            <p className="hint">
              Results are added step by step. Each entry is appended, so readers see what
              you added rather than a rewritten argument.
            </p>

            {finding.entries.map((entry) => (
              <div key={entry.id} className="composer__entry">
                <FindingEntryView entry={entry} members={finding.spectra} />
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--sm"
                  onClick={() => handleDeleteEntry(entry.id)}
                >
                  Delete entry
                </button>
              </div>
            ))}

            <div className="composer__new-entry">
              <label className="field">
                <span>Add an entry</span>
                <select
                  value={entryKind}
                  onChange={(e) => setEntryKind(e.target.value as FindingEntryKind)}
                >
                  {ENTRY_KINDS.map((kind) => (
                    <option key={kind.value} value={kind.value}>
                      {kind.label} — {kind.hint}
                    </option>
                  ))}
                </select>
              </label>
              <textarea
                value={entryBody}
                onChange={(e) => setEntryBody(e.target.value)}
                rows={3}
                placeholder="Caption or commentary for this entry…"
              />
              <Button onClick={handleAppendEntry}>Append entry</Button>
            </div>
          </Card>

          {finding.state === 'draft' && (
            <Card title="Publish">
              {unpublishedMembers.length > 0 && (
                <p className="warning">
                  {unpublishedMembers.length} attached spectr
                  {unpublishedMembers.length === 1 ? 'um is' : 'a are'} still private.
                  Publish {unpublishedMembers.length === 1 ? 'it' : 'them'} first, or remove{' '}
                  {unpublishedMembers.length === 1 ? 'it' : 'them'} — a public finding
                  can't reference private data.
                </p>
              )}
              <label className="field">
                <span>License</span>
                <select value={licenseId} onChange={(e) => setLicenseId(e.target.value)}>
                  {licenses.map((license) => (
                    <option key={license.id} value={license.id}>
                      {license.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                variant="primary"
                onClick={handlePublish}
                disabled={finding.spectra.length === 0 || unpublishedMembers.length > 0}
              >
                Publish finding
              </Button>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
