import { useEffect, useState } from 'react';
import {
  citationDownloadUrl,
  getCitation,
  spectrumDownloadUrl,
  DOWNLOAD_FORMATS,
  type CitationFormat,
  type DownloadFormat,
  type Stage,
} from '../api/exports';
import { useToast } from './Toast';
import { Button, Card } from './ui';

const CITATION_FORMATS: Array<{ value: CitationFormat; label: string }> = [
  { value: 'bibtex', label: 'BibTeX' },
  { value: 'ris', label: 'RIS / EndNote' },
  { value: 'text', label: 'Plain text' },
];

/** Download + citation, together on purpose.
 *
 * These are the two halves of "take this data and use it": the numbers, and
 * the credit. Separating them into different corners of the UI is how
 * repositories end up widely downloaded and rarely cited. */
export default function ExportPanel({
  spectrumId,
  hasPipeline,
}: {
  spectrumId: string;
  hasPipeline: boolean;
}) {
  const { notify } = useToast();
  const [format, setFormat] = useState<DownloadFormat>('csv');
  const [stage, setStage] = useState<Stage>('processed');
  const [citationFormat, setCitationFormat] = useState<CitationFormat>('bibtex');
  const [citation, setCitation] = useState('');

  useEffect(() => {
    getCitation(spectrumId, citationFormat)
      .then(setCitation)
      .catch(() => setCitation(''));
  }, [spectrumId, citationFormat]);

  async function copyCitation() {
    try {
      await navigator.clipboard.writeText(citation);
      notify('Citation copied.', 'success');
    } catch {
      // Clipboard access is denied in some contexts (insecure origin,
      // permissions policy); the textarea is selectable as the fallback.
      notify('Select the text and copy it manually.', 'error');
    }
  }

  const activeFormat = DOWNLOAD_FORMATS.find((f) => f.value === format);

  return (
    <Card title="Download &amp; cite">
      <div className="export-grid">
        <div>
          <h4>Get the data</h4>
          <label className="field">
            <span>Format</span>
            <select value={format} onChange={(e) => setFormat(e.target.value as DownloadFormat)}>
              {DOWNLOAD_FORMATS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {activeFormat && <small className="hint">{activeFormat.hint}</small>}
          </label>

          {hasPipeline && (
            <div className="segmented" role="group" aria-label="Processing stage">
              <button
                type="button"
                className="segmented__option"
                aria-pressed={stage === 'processed'}
                onClick={() => setStage('processed')}
              >
                Processed
              </button>
              <button
                type="button"
                className="segmented__option"
                aria-pressed={stage === 'raw'}
                onClick={() => setStage('raw')}
              >
                Raw
              </button>
            </div>
          )}

          {/* A real anchor, not a fetch-into-Blob: the browser applies the
              server's filename and streams to disk without buffering the
              whole spectrum in memory. */}
          <a
            className="ui-button ui-button--primary"
            href={spectrumDownloadUrl(spectrumId, format, stage)}
            download
          >
            Download
          </a>
          <p className="hint">
            Every export carries its own provenance header — accession, contributor, ORCID,
            license and the exact processing steps applied.
          </p>
        </div>

        <div>
          <h4>Cite this spectrum</h4>
          <label className="field">
            <span>Style</span>
            <select
              value={citationFormat}
              onChange={(e) => setCitationFormat(e.target.value as CitationFormat)}
            >
              {CITATION_FORMATS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <textarea className="citation-box" value={citation} readOnly rows={6} />
          <div className="button-row">
            <Button size="sm" onClick={copyCitation} disabled={!citation}>
              Copy
            </Button>
            <a
              className="ui-button ui-button--sm"
              href={citationDownloadUrl(spectrumId, citationFormat)}
              download
            >
              Download
            </a>
          </div>
        </div>
      </div>
    </Card>
  );
}
