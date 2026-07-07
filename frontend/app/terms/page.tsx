import type { Metadata } from "next";
import { LegalShell } from "@/components/legal/LegalShell";

export const metadata: Metadata = { title: "Terms of Service — pondas", robots: { index: true }, alternates: { canonical: "/terms" } };

export default function Terms() {
  return (
    <LegalShell title="Terms of Service" updated="June 19, 2026">
      <p>
        These Terms of Service (&ldquo;Terms&rdquo;) are a binding agreement between you and{" "}
        <strong>Hyunjung Yoon</strong>, an individual operating the service known as{" "}
        <strong>pondas</strong> (&ldquo;pondas,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;), which is available at
        pondas.ai and related applications (the &ldquo;Service&rdquo;). By creating an account or using the Service,
        you agree to these Terms and to our <a href="/privacy">Privacy Policy</a> and{" "}
        <a href="/refunds">Refund &amp; Cancellation Policy</a>, which are incorporated by reference. If you do not
        agree, do not use the Service.
      </p>

      <h2>1. Eligibility &amp; age</h2>
      <p>
        You must be at least <strong>13 years old</strong> to use the Service. If you are under 18 (or the age of
        majority where you live), you may use the Service only with the consent and supervision of a parent or legal
        guardian, who agrees to these Terms on your behalf. <strong>You must be at least 18</strong> (or the age of
        majority where you live) to purchase a subscription, buy credits, or otherwise enter into a paid
        transaction. We do not knowingly allow children under 13 to use the Service.
      </p>

      <h2>2. Your account</h2>
      <p>
        Authentication is provided through our identity provider. You are responsible for the activity under your
        account and for keeping your credentials secure. Provide accurate information and keep it current. You may
        not share, sell, or transfer your account.
      </p>

      <h2>3. The Service</h2>
      <p>
        pondas lets you direct teams of AI agents to plan, design, and build software and related content. The
        agents run on third-party AI models and cloud infrastructure. The Service is provided on an ongoing basis
        and may change, improve, or be discontinued over time.
      </p>

      <h2>4. Credits, plans &amp; billing</h2>
      <p>
        The Service is metered in <strong>credits</strong>. You receive credits through a subscription plan
        (refilled each billing period), through one-time credit packs, or as promotional/free credits. Agent work
        consumes credits based on the model tier and scope of the task. Prices and credit amounts are shown at the
        point of purchase and may change prospectively.
      </p>
      <ul>
        <li><strong>Credits have no cash value</strong>, are non-transferable, and are not redeemable for money except where required by law.</li>
        <li>Promotional/free credits may expire and are limited to one grant per account; abuse (including multiple accounts) may result in forfeiture.</li>
        <li>Payments are processed by our payment processor. We do not store full payment card details.</li>
      </ul>

      <h2>5. Subscriptions, automatic renewal &amp; cancellation</h2>
      <p>
        Subscriptions <strong>automatically renew</strong> at the end of each billing period (monthly unless stated
        otherwise) and your payment method is charged the then-current price, until you cancel. By subscribing you
        give <strong>express affirmative consent</strong> to these recurring charges.
      </p>
      <ul>
        <li>You may <strong>cancel at any time</strong> from your account billing settings; cancellation stops future renewals.</li>
        <li>After cancellation you keep access and any remaining subscription credits until the end of the current paid period.</li>
        <li>See our <a href="/refunds">Refund &amp; Cancellation Policy</a> for refund details.</li>
      </ul>

      <h2>6. AI outputs &amp; intellectual property</h2>
      <p>
        As between you and us, you own the inputs you provide and, to the extent we hold any rights in the outputs
        the agents generate for you (&ldquo;Outputs&rdquo;), we assign those rights to you. We claim no ownership of
        your Outputs.
      </p>
      <ul>
        <li>
          AI-generated material may not be eligible for copyright or other protection, and may resemble material
          generated for other users. You are solely responsible for reviewing, testing, and validating Outputs
          before relying on or distributing them.
        </li>
        <li>You are responsible for ensuring your use of Outputs (including any generated code) complies with applicable law and third-party rights.</li>
        <li>You grant us a limited license to host and process your inputs and Outputs solely to operate and improve the Service. See the <a href="/privacy">Privacy Policy</a> for how we handle your data.</li>
      </ul>

      <h2>7. Acceptable use</h2>
      <p>You agree not to use the Service to:</p>
      <ul>
        <li>generate or facilitate anything illegal, harmful, infringing, deceptive, or that violates third-party rights;</li>
        <li>create malware, conduct attacks, or compromise security;</li>
        <li>build or train a competing AI model or service, or scrape/resell the Service;</li>
        <li>circumvent usage limits, credits, rate limits, or security measures;</li>
        <li>violate the acceptable-use policies of our underlying AI providers (including Anthropic), which apply to your use.</li>
      </ul>
      <p>We may suspend or terminate accounts that violate these Terms.</p>

      <h2>8. Third-party services</h2>
      <p>
        The Service relies on third parties (including AI model providers, payment processing, authentication, and
        cloud hosting). Your use may also be subject to their terms. We are not responsible for third-party
        services and do not control their availability.
      </p>

      <h2>9. Disclaimers</h2>
      <p>
        THE SERVICE AND ALL OUTPUTS ARE PROVIDED <strong>&ldquo;AS IS&rdquo; AND &ldquo;AS AVAILABLE,&rdquo;</strong>{" "}
        WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR
        PURPOSE, AND NON-INFRINGEMENT. AI systems can produce inaccurate, incomplete, or &ldquo;hallucinated&rdquo;
        results. We do not warrant that the Service will be uninterrupted, secure, or error-free, or that Outputs
        will be accurate, reliable, or fit for any purpose.
      </p>

      <h2>10. Limitation of liability</h2>
      <p>
        TO THE MAXIMUM EXTENT PERMITTED BY LAW, WE WILL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL,
        CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR FOR LOST PROFITS, DATA, OR GOODWILL. OUR TOTAL LIABILITY FOR ANY
        CLAIM ARISING FROM OR RELATING TO THE SERVICE WILL NOT EXCEED THE GREATER OF (A) THE AMOUNTS YOU PAID US IN
        THE 12 MONTHS BEFORE THE EVENT GIVING RISE TO THE CLAIM, OR (B) USD $100. Some jurisdictions do not allow
        certain limitations, so some of the above may not apply to you.
      </p>

      <h2>11. Indemnification</h2>
      <p>
        You agree to indemnify and hold harmless Hyunjung Yoon (pondas) from claims, losses, and expenses
        (including reasonable legal fees) arising from your use of the Service, your Outputs, or your violation of
        these Terms or applicable law, except to the extent caused by our own breach.
      </p>

      <h2>12. Termination</h2>
      <p>
        You may stop using the Service at any time. We may suspend or terminate your access if you violate these
        Terms or if we discontinue the Service. Sections that by their nature should survive (including IP,
        disclaimers, liability, indemnity, and dispute resolution) survive termination.
      </p>

      <h2>13. Changes to these Terms</h2>
      <p>
        We may update these Terms. If changes are material, we will provide reasonable notice (e.g., by email or
        in-product). Continued use after changes take effect means you accept the updated Terms.
      </p>

      <h2>14. Governing law &amp; dispute resolution</h2>
      <p>
        These Terms are governed by the laws of the <strong>Republic of Korea</strong>, without regard to conflict
        of law rules. Mandatory consumer-protection rights in your place of residence (including, for California
        residents, the CCPA/CPRA, and for residents of the EU/EEA, the GDPR and local consumer law) continue to
        apply where required.
      </p>
      <p>
        <strong>Binding arbitration.</strong> Except where prohibited by law, any dispute arising out of or relating
        to these Terms or the Service will be resolved by <strong>final and binding arbitration</strong> on an
        individual basis. <strong>You and we waive any right to a jury trial and to participate in a class action
        or class-wide arbitration.</strong> Where binding arbitration or a class waiver is not enforceable for you
        under applicable law, that exclusion does not apply to you.
      </p>

      <h2>15. Contact</h2>
      <p>
        Questions about these Terms: <a href="mailto:harris@vlippers.com">harris@vlippers.com</a>.
      </p>
    </LegalShell>
  );
}
