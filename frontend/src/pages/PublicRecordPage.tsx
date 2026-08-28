import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getPublicSpectrum, type PublicSpectrumRecord } from '../api/community';

export default function PublicRecordPage() {
  const { id = '' } = useParams();
  const [record, setRecord] = useState<PublicSpectrumRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getPublicSpectrum(id).then(setRecord).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [id]);

  async function copyCitation() {
    if (!record) return;
    await navigator.clipboard.writeText(`${window.location.origin}${record.canonical_path}`);
    setCopied(true);
  }

  if (error) return <p className="error">{error}</p>;
  if (!record) return <p>Loading public record…</p>;
  const metadata = record.metadata ?? {};

  return (
    <section>
      <p className="eyebrow">Public spectrum record</p>
      <h1>{record.title ?? 'Untitled spectrum'}</h1>
      <p>{record.description}</p>
      <p className="hint">
        Contributor: {record.author.profile_path ? <Link to={record.author.profile_path}>{record.author.display_name}</Link> : record.author.display_name}
        {record.author.orcid_id ? ` · ORCID ${record.author.orcid_id}` : ''}
      </p>
      <div className="field-row">
        <a className="button" href={record.download_url}>Download data</a>
        <a className="button button--secondary" href={record.citation_url}>Citation</a>
        <button type="button" onClick={copyCitation}>{copied ? 'Link copied' : 'Copy link'}</button>
      </div>
      <h2>Scientific context</h2>
      <dl>
        <dt>Modality</dt><dd>{record.modality}</dd>
        <dt>License</dt><dd>{record.license ? <a href={record.license.url}>{record.license.name}</a> : 'Not available'}</dd>
        <dt>DOI evidence</dt><dd>{record.publication?.doi ?? 'No linked DOI'}</dd>
      </dl>
      <h2>Confirmed metadata</h2>
      <pre>{JSON.stringify(metadata, null, 2)}</pre>
      <h2>Reproducibility provenance</h2>
      <pre>{JSON.stringify(record.provenance, null, 2)}</pre>
    </section>
  );
}