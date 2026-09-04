import type { Metadata } from "next";

import { LegalDoc } from "~/components/legal-doc";

export const metadata: Metadata = { title: "Privacy Policy · Spectra Insight" };

export default function PrivacyPage() {
  return (
    <LegalDoc title="Privacy Policy" updated="August 2026">
      <section>
        <h2>What we collect</h2>
        <p>
          Signing in with Google or GitHub gives us your name, email address, and
          profile photo — nothing else, and we never see a password. Signing in
          with ORCID gives us your ORCID iD and name; ORCID may not release an
          email, in which case your account simply has none. Guests are assigned
          an anonymous session identifier and provide no personal information.
        </p>
      </section>

      <section>
        <h2>How it&apos;s used</h2>
        <p>
          Your name (and ORCID iD, if you signed in with it or added it) is shown
          as the contributor on findings and spectra you choose to publish, and on
          your public profile. Your email is used for account identity only — no
          marketing — and is never displayed publicly or sold to third parties.
          Your follower/following relationships and your votes, shares, and
          comments on published records are public.
        </p>
      </section>

      <section>
        <h2>Where data lives</h2>
        <p>
          Account metadata lives in our PostgreSQL database; uploaded spectral
          files live in S3-compatible object storage (Cloudflare R2 in
          production). Error diagnostics may be processed by Sentry. When no
          built-in parser recognizes a file, its header is sent to our language
          model provider (OpenRouter) to extract metadata — the header text
          only, never the data body, and not tied to your identity.
        </p>
        <p>
          By default those calls route through OpenRouter&rsquo;s free-model
          router, which selects a different model for each request. We record
          which model answered and show it next to the result, so the
          provenance of machine-written metadata stays inspectable. The model
          providers&rsquo; own retention terms apply to whatever we send them;
          we do not control those.
        </p>
        <p>
          You can take us out of that path entirely. Add your own provider API
          key under Settings and every model-backed feature — header parsing,
          structure detection, abstract summaries, filename suggestions and the
          lab consultant — calls your provider on your account instead of ours.
          Your key is encrypted at rest, is never returned by the API, and is
          deleted when you close your account. While your key is in use, the
          metadata templates derived from your files are also kept out of the
          shared format caches that other accounts read.
        </p>
      </section>

      <section>
        <h2>Your choices</h2>
        <p>
          Unpublished (draft) data is visible only to you. Your profile can be set
          to non-public during onboarding or later in settings. You can stop using
          the service at any time; contact us to request account deletion.
          Published data remains available under its license, as with any
          scientific repository.
        </p>
      </section>

      <section>
        <h2>Contact</h2>
        <p>
          Privacy questions and deletion requests:{" "}
          <a className="hover:underline" href="mailto:hello@spectra-in.site">
            hello@spectra-in.site
          </a>
          .
        </p>
      </section>
    </LegalDoc>
  );
}
