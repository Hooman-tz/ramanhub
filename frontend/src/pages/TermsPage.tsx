import { Card } from '../components/ui';

/* PLACEHOLDER LEGAL TEXT — review before public launch. Written to be
 * accurate to how the platform actually works today, but it has not been
 * reviewed by a lawyer. */
export default function TermsPage() {
  return (
    <div className="confirm-page">
      <h1>Terms of Service</h1>
      <Card>
        <p className="hint">Last updated: August 2026 · Draft — under review.</p>

        <h3>The service</h3>
        <p>
          RamanHub is a platform for sharing, processing, and discovering Raman spectroscopy
          data. It is provided as-is, without warranty of any kind, during its early-access
          period.
        </p>

        <h3>Your data</h3>
        <p>
          Data you upload stays private (draft) until you explicitly publish it. Raw uploaded
          files are immutable — processing never modifies your original data. You may use the
          platform as a guest without an account; guest work is transferred to your account if
          you later sign in from the same browser session.
        </p>

        <h3>Publishing and licensing</h3>
        <p>
          Publishing a spectrum makes it publicly visible and requires choosing a license —
          CC-BY 4.0 by default, CC0 optionally. By publishing you confirm you have the right to
          share the data under that license. Published data may be downloaded, reused, and
          redistributed by others under the chosen license's terms. Publication is intended to
          be permanent, in the spirit of a scientific data repository.
        </p>

        <h3>Acceptable use</h3>
        <p>
          Don't upload data you don't have the right to share, content that isn't spectral
          data, or malicious files. Don't abuse the voting/commenting system or attempt to
          circumvent rate limits or access controls. Accounts that do may be disabled.
        </p>
      </Card>
    </div>
  );
}
