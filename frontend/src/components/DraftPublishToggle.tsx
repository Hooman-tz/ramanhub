import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getLicenses, publishSpectrum, updateSpectrum, type License, type Spectrum } from '../api/client';
import { lookupDoi, type DoiMetadata } from '../api/visualization';
import { useAuth } from '../auth/useAuth';
import { Button, Card, InputField, SelectField } from './ui';

interface Props {
  spectrum: Spectrum;
  onPublished: (updated: Spectrum) => void;
}

/** The publish flow for a draft: optional DOI lookup (auto-populates paper
 * metadata for review — never auto-submitted), mandatory license, optional
 * embargo. Renders nothing beyond the state badge once published. */
export default function DraftPublishToggle({ spectrum, onPublished }: Props) {
  const { user } = useAuth();
  const [licenses, setLicenses] = useState<License[]>([]);
  const [licenseId, setLicenseId] = useState('');
  const [embargoDate, setEmbargoDate] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- DOI lookup (auto-populate paper metadata instead of manual entry) ---
  // Looked-up metadata is shown as a read-only preview for the user to
  // review (never auto-submitted). "Use this metadata" persists
  // title/description onto the draft via PATCH /spectra/{id}. The raw DOI
  // string itself (once looked up, regardless of whether its metadata was
  // "applied") is sent along with the publish request below — that's what
  // marks the spectrum DOI-verified for Module 4's trust-tier search filter.
  const [doiInput, setDoiInput] = useState('');
  const [doiLookupLoading, setDoiLookupLoading] = useState(false);
  const [doiMetadata, setDoiMetadata] = useState<DoiMetadata | null>(null);
  const [doiNotFound, setDoiNotFound] = useState(false);
  const [doiError, setDoiError] = useState<string | null>(null);
  const [applyingDoiMetadata, setApplyingDoiMetadata] = useState(false);

  useEffect(() => {
    if (spectrum.state !== 'draft') return;
    getLicenses()
      .then(setLicenses)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [spectrum.state]);

  async function handleDoiLookup() {
    if (!doiInput.trim()) {
      setDoiError('Enter a DOI first.');
      return;
    }
    setDoiError(null);
    setDoiNotFound(false);
    setDoiMetadata(null);
    try {
      setDoiLookupLoading(true);
      const result = await lookupDoi(doiInput.trim());
      if (result === null) {
        setDoiNotFound(true);
      } else {
        setDoiMetadata(result);
      }
    } catch (err) {
      setDoiError(err instanceof Error ? err.message : String(err));
    } finally {
      setDoiLookupLoading(false);
    }
  }

  async function handleApplyDoiMetadata() {
    if (!doiMetadata) return;
    try {
      setApplyingDoiMetadata(true);
      setDoiError(null);
      const authorsSuffix = doiMetadata.authors.length ? ` (${doiMetadata.authors.join(', ')})` : '';
      const journalSuffix = doiMetadata.journal
        ? ` — ${doiMetadata.journal}${doiMetadata.year ? ` (${doiMetadata.year})` : ''}`
        : '';
      const updated = await updateSpectrum(spectrum.id, {
        title: doiMetadata.title ?? spectrum.title,
        description: `${authorsSuffix.trim()}${journalSuffix}`.trim() || spectrum.description,
      });
      onPublished(updated);
    } catch (err) {
      setDoiError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplyingDoiMetadata(false);
    }
  }

  async function handlePublish() {
    if (!licenseId) {
      setError('Choose a license first.');
      return;
    }
    try {
      setPublishing(true);
      setError(null);
      const updated = await publishSpectrum(spectrum.id, {
        license_id: licenseId,
        embargo_release_at: embargoDate ? new Date(embargoDate).toISOString() : null,
        // Only send a DOI that actually resolved via lookup (doiMetadata is
        // set) — an unverified/typo'd DOI string shouldn't be able to mark
        // a spectrum "DOI-verified" for the trust-tier search filter.
        doi: doiMetadata ? doiInput.trim() : null,
      });
      onPublished(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPublishing(false);
    }
  }

  if (spectrum.state !== 'draft') return null;

  // Guests keep drafts + the full processing toolbox, but publishing grants
  // a license to the commons — that needs a real identity. Their work
  // migrates to the account automatically on sign-in.
  if (user?.is_guest) {
    return (
      <Card title="Publish to the commons">
        <p className="hint">
          You're working as a guest. Sign in with Google to publish this spectrum, link a
          paper DOI, and keep it in your private library — everything you've done here
          carries over to your account.
        </p>
        <Link to="/login" className="ui-button ui-button--primary">
          Sign in to publish
        </Link>
      </Card>
    );
  }

  return (
    <Card title="Publish to the commons">
      <p className="hint">
        This spectrum is a private draft — process and explore freely. Publishing is an
        explicit, separate action.
      </p>

      <InputField
        label="Paper DOI (optional)"
        placeholder="10.1021/acs.analchem.xxxxxxx"
        value={doiInput}
        onChange={(e) => {
          setDoiInput(e.target.value);
          setDoiMetadata(null);
          setDoiNotFound(false);
        }}
        hint="A resolved DOI marks this spectrum DOI-verified in search."
      />
      <Button onClick={handleDoiLookup} loading={doiLookupLoading}>
        Look up
      </Button>

      {doiError && <p className="error">{doiError}</p>}
      {doiNotFound && <p className="hint">No metadata found for that DOI.</p>}

      {doiMetadata && (
        <Card strong title={doiMetadata.title ?? '(no title found)'}>
          {doiMetadata.authors.length > 0 && <p>{doiMetadata.authors.join(', ')}</p>}
          {(doiMetadata.journal || doiMetadata.year) && (
            <p className="hint">
              {doiMetadata.journal ?? ''} {doiMetadata.year ? `(${doiMetadata.year})` : ''}
            </p>
          )}
          {doiMetadata.url && (
            <p>
              <a href={doiMetadata.url} target="_blank" rel="noreferrer">
                {doiMetadata.url}
              </a>
            </p>
          )}
          <p className="hint">
            This is a preview only — review it, then apply it to this draft's title/description
            if it's correct.
          </p>
          <Button onClick={handleApplyDoiMetadata} loading={applyingDoiMetadata}>
            Use this metadata
          </Button>
        </Card>
      )}

      <SelectField
        label="License"
        value={licenseId}
        onChange={(e) => setLicenseId(e.target.value)}
      >
        <option value="">Select a license...</option>
        {licenses.map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
      </SelectField>

      <InputField
        label="Embargo release date (optional)"
        type="date"
        value={embargoDate}
        onChange={(e) => setEmbargoDate(e.target.value)}
        hint="Private until this date, then automatically public — for pre-publication data."
      />

      <Button variant="primary" onClick={handlePublish} loading={publishing}>
        Publish
      </Button>

      {error && <p className="error">{error}</p>}
    </Card>
  );
}
