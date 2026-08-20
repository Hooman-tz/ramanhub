import { Card } from '../components/ui';

/* PLACEHOLDER LEGAL TEXT — review before public launch. Written to be
 * accurate to how the platform actually works today, but it has not been
 * reviewed by a lawyer. */
export default function PrivacyPage() {
  return (
    <div className="confirm-page">
      <h1>Privacy Policy</h1>
      <Card>
        <p className="hint">Last updated: August 2026 · Draft — under review.</p>

        <h3>What we collect</h3>
        <p>
          Signing in with Google gives us your name, email address, and profile photo —
          nothing else from your Google account, and we never see a password. You may
          optionally add an ORCID iD to your profile. Guests are assigned an anonymous
          session identifier and provide no personal information.
        </p>

        <h3>How it's used</h3>
        <p>
          Your name (and ORCID, if linked) is shown as the contributor on spectra you choose
          to publish. Your email is used for account identity only — no marketing, and it is
          never displayed publicly or shared with third parties.
        </p>

        <h3>Where data lives</h3>
        <p>
          Account metadata lives in our database; uploaded spectral files live in object
          storage (Cloudflare R2). Error diagnostics may be processed by Sentry. Uploaded
          file headers that no built-in parser recognizes are sent to Anthropic's API for
          metadata extraction — header content only, never tied to your identity.
        </p>

        <h3>Your choices</h3>
        <p>
          Unpublished (draft) data is visible only to you. You can stop using the service at
          any time; contact us to request account deletion. Published data remains available
          under its license, as with any scientific repository.
        </p>
      </Card>
    </div>
  );
}
