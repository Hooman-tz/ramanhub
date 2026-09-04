import type { Metadata } from "next";

import { LegalDoc } from "~/components/legal-doc";

export const metadata: Metadata = { title: "Terms of Service · Spectra Insight" };

export default function TermsPage() {
  return (
    <LegalDoc title="Terms of Service" updated="August 2026">
      <section>
        <h2>The service</h2>
        <p>
          Spectra Insight is a platform for sharing, processing, and discovering
          spectroscopy data (Raman first). It is provided as-is, without warranty
          of any kind, during its early-access period. Features may change or be
          removed while the beta is running.
        </p>
      </section>

      <section>
        <h2>Accounts and sign-in</h2>
        <p>
          You can use the platform as a guest without an account. Signing in with
          Google, GitHub, or ORCID creates an account; work you did as a guest in
          the same browser session is transferred to it on first sign-in. You are
          responsible for activity under your account. We may disable accounts
          that abuse the service.
        </p>
      </section>

      <section>
        <h2>Your data</h2>
        <p>
          Data you upload stays private (draft) until you explicitly publish it.
          Raw uploaded files are immutable — processing is recorded as a versioned
          ledger and never modifies your original data.
        </p>
      </section>

      <section>
        <h2>Publishing and licensing</h2>
        <p>
          Publishing a finding or spectrum makes it publicly visible and requires
          a license — CC-BY 4.0 by default, CC0 optionally. By publishing you
          confirm you have the right to share the data under that license.
          Published data may be downloaded, reused, and redistributed by others
          under that license&apos;s terms. Publication is intended to be
          permanent, in the spirit of a scientific data repository; contact us if
          a published record must be retracted.
        </p>
      </section>

      <section>
        <h2>Acceptable use</h2>
        <p>
          Don&apos;t upload data you don&apos;t have the right to share, content
          that isn&apos;t spectral data, or malicious files. Don&apos;t abuse the
          voting, following, sharing, or commenting systems, and don&apos;t try to
          circumvent rate limits or access controls.
        </p>
      </section>

      <section>
        <h2>Changes</h2>
        <p>
          We may update these terms as the platform develops. Material changes
          will be noted on this page with a new &ldquo;last updated&rdquo; date.
        </p>
      </section>
    </LegalDoc>
  );
}
