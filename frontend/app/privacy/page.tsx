import type { Metadata } from "next";
import { LegalShell } from "@/components/legal/LegalShell";

export const metadata: Metadata = { title: "Privacy Policy — pondas", robots: { index: true } };

export default function Privacy() {
  return (
    <LegalShell title="Privacy Policy" updated="June 19, 2026">
      <p>
        This Privacy Policy explains how <strong>Hyunjung Yoon</strong>, operating <strong>pondas</strong>{" "}
        (&ldquo;we,&rdquo; &ldquo;us&rdquo;), collects, uses, and shares personal information when you use pondas.ai
        and related applications (the &ldquo;Service&rdquo;). It includes disclosures for residents of California
        (CCPA/CPRA) and the EU/EEA &amp; UK (GDPR).
      </p>

      <h2>1. Information we collect</h2>
      <ul>
        <li><strong>Account &amp; identifiers</strong> — name, email, and account ID, via our authentication provider.</li>
        <li><strong>Your inputs &amp; Outputs</strong> — prompts, instructions, uploaded context, and the content the agents generate for you.</li>
        <li><strong>Usage &amp; device data</strong> — actions in the product, log data, IP address, browser/device info, and approximate location derived from IP.</li>
        <li><strong>Payment data</strong> — handled by our payment processor; we receive limited billing details (e.g., plan, last4, status) and <strong>do not store full card numbers</strong>.</li>
        <li><strong>Cookies</strong> — strictly necessary cookies for authentication and security; analytics cookies only with consent where required (see §9).</li>
      </ul>

      <h2>2. How we use information</h2>
      <ul>
        <li>To provide, operate, secure, and improve the Service and run the AI agents you direct;</li>
        <li>To process payments, credits, and subscriptions;</li>
        <li>To communicate with you about your account, security, and changes to the Service;</li>
        <li>To prevent fraud and abuse and to comply with legal obligations.</li>
      </ul>

      <h2>3. AI processing &amp; model training</h2>
      <p>
        Your inputs and Outputs are sent to our AI model provider(s) to perform the tasks you request.{" "}
        <strong>We do not use your inputs or Outputs to train our own AI models, and we do not sell your content.</strong>{" "}
        Our primary model provider (Anthropic) does not train its models on data submitted through its API by
        default. We use your content only to operate, secure, and improve the Service.
      </p>

      <h2>4. Legal bases (GDPR)</h2>
      <p>Where the GDPR applies, we process personal data on these bases:</p>
      <ul>
        <li><strong>Performance of a contract</strong> — to provide the Service you sign up for;</li>
        <li><strong>Legitimate interests</strong> — to secure, maintain, and improve the Service and prevent abuse;</li>
        <li><strong>Consent</strong> — for non-essential cookies/analytics and optional communications; and</li>
        <li><strong>Legal obligation</strong> — to meet tax, accounting, and compliance requirements.</li>
      </ul>

      <h2>5. How we share information (service providers / subprocessors)</h2>
      <p>
        We share personal information with service providers who process it on our behalf to run the Service, under
        contracts that limit their use of it:
      </p>
      <ul>
        <li><strong>Anthropic</strong> — AI model inference;</li>
        <li><strong>Stripe</strong> — payment processing;</li>
        <li><strong>Clerk</strong> — authentication;</li>
        <li><strong>Vercel &amp; Railway</strong> — application and database hosting;</li>
        <li><strong>E2B</strong> — sandboxed code execution;</li>
        <li><strong>Google Analytics &amp; Amplitude</strong> — product analytics (loaded only after you accept analytics cookies).</li>
      </ul>
      <p>
        We may also disclose information to comply with law, enforce our Terms, or protect rights and safety, and in
        connection with a business transfer. <strong>We do not sell your personal information, and we do not share
        it for cross-context behavioral advertising</strong> as those terms are defined under California law.
      </p>

      <h2>6. Data retention</h2>
      <p>
        We keep personal information for as long as your account is active and as needed to provide the Service,
        then for a reasonable period to meet legal, tax, security, and dispute-resolution needs, after which it is
        deleted or de-identified. You can request deletion as described in §8.
      </p>

      <h2>7. International transfers</h2>
      <p>
        We and our service providers may process your information in the United States and other countries. Where
        required (e.g., for EU/EEA/UK data), transfers rely on appropriate safeguards such as the European
        Commission&rsquo;s Standard Contractual Clauses.
      </p>

      <h2>8. Your rights</h2>
      <p>
        <strong>California (CCPA/CPRA).</strong> You have the right to know/access the categories and specific
        pieces of personal information we collect, to delete it, to correct inaccurate information, to opt out of
        sale or sharing, and to limit the use of sensitive personal information. We do not sell or share personal
        information, and we do not use sensitive personal information for purposes that require an opt-out. We will
        not discriminate against you for exercising these rights.
      </p>
      <p>
        <strong>EU/EEA &amp; UK (GDPR).</strong> You have the right to access, rectify, erase, restrict, and object
        to processing, the right to data portability, the right to withdraw consent, and the right to lodge a
        complaint with your supervisory authority.
      </p>
      <p>
        To exercise any right, email <a href="mailto:harris@vlippers.com">harris@vlippers.com</a>. We will verify
        and respond within the timeframes required by law. You may use an authorized agent where permitted.
      </p>

      <h2>9. Cookies &amp; tracking</h2>
      <p>
        We use strictly necessary cookies to keep you signed in and secure. We also use{" "}
        <strong>analytics cookies via Google Analytics and Amplitude</strong> to understand product usage and
        improve pondas. Analytics cookies load <strong>only after you accept</strong> them in our cookie banner
        (opt-in consent, as required in the EU/EEA/UK); you can decline, and you can change your choice anytime via
        the &ldquo;Cookie preferences&rdquo; link in the footer. We honor opt-out signals (including Global Privacy
        Control) where applicable.
      </p>

      <h2>10. Children</h2>
      <p>
        The Service is not directed to children under 13, and we do not knowingly collect personal information from
        them. If you believe a child under 13 has provided us information, contact us and we will delete it.
      </p>

      <h2>11. Security</h2>
      <p>
        We use reasonable technical and organizational measures to protect personal information. No method of
        transmission or storage is completely secure, and we cannot guarantee absolute security.
      </p>

      <h2>12. Changes to this Policy</h2>
      <p>
        We may update this Policy and will revise the &ldquo;Last updated&rdquo; date; material changes will be
        communicated as required by law.
      </p>

      <h2>13. Contact</h2>
      <p>
        Privacy questions or requests: <a href="mailto:harris@vlippers.com">harris@vlippers.com</a> (Hyunjung Yoon,
        operating pondas).
      </p>
    </LegalShell>
  );
}
