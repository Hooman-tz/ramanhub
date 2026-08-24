import { useEffect, useState } from 'react';
import {
  findingBundleUrl,
  findingCitationUrl,
  getFindingCitation,
} from '../api/findings';
import { useToast } from './Toast';
import { Button, Card } from './ui';

type CitationFormat = 'bibtex' | 'ris' | 'text';

const FORMATS: Array<{ value: CitationFormat; label: string }> = [
  { value: 'bibtex', label: 'BibTeX' },
  { value: 'ris', label: 'RIS / EndNote' },
  { value: 'text', label: 'Plain text' },
];

/** Download-and-cite for a whole finding.
 *
 * The bundle is the reproducibility artifact: raw and processed arrays per
 * spectrum plus the ledger that connects them, so a reader can verify the
 * processing rather than trust it. */
export default function FindingExport({
  findingId,
  spectrumCount,
}: {
  findingId: string;
  spectrumCount: number;
}) {
  const { notify } = useToast();
  const [format, setFormat] = useState<CitationFormat>('bibtex');
  const [citation, setCitation] = useState('');

  useEffect(() => {
    getFindingCitation(findingId, format)
      .then(setCitation)
      .catch(() => setCitation(''));
  }, [findingId, format]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(citation);
      notify('Citation copied.', 'success');
    } catch {
      notify('Select the text and copy it manually.', 'error');
    }
  }

  return (
    <Card title="Download &amp; cite">
      <div className="export-grid">
        <div>
          <h4>Take it with you</h4>
          <p className="hint">
            One archive with all {spectrumCount} spectr{spectrumCount === 1 ? 'um' : 'a'} —
            raw and processed, plus the processing ledger for each, a manifest with
            checksums, and a citation. Raw plus ledger regenerates processed, so the
            analysis can be verified rather than taken on trust.
          </p>
          <a className="ui-button ui-button--primary" href={findingBundleUrl(findingId)} download>
            Download bundle (.zip)
          </a>
        </div>

        <div>
          <h4>Cite this finding</h4>
          <label className="field">
            <span>Style</span>
            <select value={format} onChange={(e) => setFormat(e.target.value as CitationFormat)}>
              {FORMATS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <textarea className="citation-box" value={citation} readOnly rows={6} />
          <div className="button-row">
            <Button size="sm" onClick={copy} disabled={!citation}>
              Copy
            </Button>
            <a
              className="ui-button ui-button--sm"
              href={findingCitationUrl(findingId, format, true)}
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
