import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getLicenses,
  publishSpectrum,
  updateSpectrum,
  verifySpectrumDoi,
  type License,
  type Spectrum,
} from '../api/client';
import { type DoiMetadata } from '../api/visualization';
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

  // --- DOI verification (persisted resolver evidence, never a bare string) ---
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
      const updated = await verifySpectrumDoi(spectrum.id, doiInput.trim());
      const snapshot = updated.provenance?.publication?.snapshot;
      setDoiMetadata((snapshot as DoiMetadata | undefined) ?? null);
      onPublished(updated);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.startsWith('API error 404')) setDoiNotFound(true);
      else setDoiError(message);
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
      });
      onPublished(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPublishing(false);
    }
  }

  if (spectrum.state !== 'draft') return null;
  const readiness = spectrum.publish_readiness;

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
      {readiness && (
        <div className={`readiness readiness--${readiness.qc_state}`}>
          <strong>{readiness.ready ? 'Ready for publication' : 'Publication checklist'}</strong>
          {readiness.blockers.length > 0 && (
            <ul>
              {readiness.blockers.map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          )}
          {readiness.warnings.length > 0 && (
            <details>
              <summary>{readiness.warnings.length} quality/provenance note(s)</summary>
              <ul>
                {readiness.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <InputField
        label="Paper DOI (optional, resolver verified)"
        placeholder="10.1021/acs.analchem.xxxxxxx"
        value={doiInput}
        onChange={(e) => {
          setDoiInput(e.target.value);
          setDoiMetadata(null);
          setDoiNotFound(false);
        }}
        hint="Verification saves a Crossref metadata snapshot before a DOI trust label is shown."
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
            This resolver snapshot is saved with the draft. Review it, then apply its title and
            description to your draft if it is correct.
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

      <Button
        variant="primary"
        onClick={handlePublish}
        loading={publishing}
        disabled={!licenseId || Boolean(readiness && !readiness.ready)}
      >
        Publish
      </Button>

      {error && <p className="error">{error}</p>}
    </Card>
  );
}
